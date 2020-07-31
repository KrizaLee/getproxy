#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals, absolute_import, division, print_function

from gevent import pool, monkey; monkey.patch_all()

import json
import logging
import os
import signal
import time

import redis
import requests
import geoip2.database
from geoip2.errors import GeoIP2Error

from .utils import signal_name, load_object

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class GetProxy(object):
    base_dir = os.path.dirname(os.path.realpath(__file__))
    filepath = os.path.join(base_dir, "proxy.py")

    def __init__(self, key, url, db):
        self.pool = pool.Pool(500)
        self.plugins = []
        self.web_proxies = []
        self.valid_proxies = []
        self.input_proxies = []
        self.proxies_hash = set()
        self.origin_ip = None
        # todo: Remove GeoIP2 database to optimize performance
        self.geoip_reader = None
        self.set_key = key
        self.client = redis.Redis.from_url(url, db)

    def _validate_proxy(self, proxy, scheme='http'):
        country = proxy.get('country')
        host = proxy.get('host')
        port = proxy.get('port')

        proxy_hash = '%s://%s:%s' % (scheme, host, port)
        if proxy_hash in self.proxies_hash:
            return

        self.proxies_hash.add(proxy_hash)
        request_proxies = {
            scheme: "%s:%s" % (host, port)
        }

        request_begin = time.time()
        try:
            response_json = requests.get(
                "%s://httpbin.org/get?show_env=1&cur=%s" % (scheme, request_begin),
                proxies=request_proxies,
                timeout=5
            ).json()
        except Exception as e:
            return

        request_end = time.time()

        if str(request_begin) != response_json.get('args', {}).get('cur', ''):
            return

        anonymity = self._check_proxy_anonymity(response_json)
        try:
            country = country or self.geoip_reader.country(host).country.iso_code
        except GeoIP2Error:
            country = None
        origin_address = self._check_origin_address(response_json)

        return {
            "hash": proxy_hash,
            "type": scheme,
            "host": host,
            "port": port,
            "origin": origin_address,
            "anonymity": anonymity,
            "country": country,
            "response_time": round(request_end - request_begin, 2),
            "from": proxy.get('from')
        }

    def _validate_proxy_list(self, proxies, timeout=300):
        valid_proxies = []

        def save_result(p):
            if p:
                valid_proxies.append(p)

        for proxy in proxies:
            self.pool.apply_async(self._validate_proxy, args=(proxy, 'http'), callback=save_result)
            self.pool.apply_async(self._validate_proxy, args=(proxy, 'https'), callback=save_result)

        self.pool.join(timeout=timeout)
        self.pool.kill()

        return valid_proxies

    def _check_proxy_anonymity(self, response):
        via = response.get('headers', {}).get('Via', '')

        if self.origin_ip in json.dumps(response):
            return 'transparent'
        elif via and via != "1.1 vegur":
            return 'anonymous'
        else:
            return 'high_anonymous'

    def _check_origin_address(self, response):
        origin = response.get('origin', '').split(', ')
        if self.origin_ip in origin:
            origin.remove(self.origin_ip)
        return origin

    def _request_force_stop(self, signum, _):
        logger.warning("[-] Cold shut down")
        self.save_proxies_to_file()
        self.save_proxies_to_redis()

        raise SystemExit()

    def _request_stop(self, signum, _):
        logger.debug("Got signal %s" % signal_name(signum))

        signal.signal(signal.SIGINT, self._request_force_stop)
        signal.signal(signal.SIGTERM, self._request_force_stop)

        logger.warning("[-] Press Ctrl+C again for a cold shutdown.")

    def init(self):
        # 1. 初始化，必须步骤
        logger.info("[*] Init")
        signal.signal(signal.SIGINT, self._request_stop)
        signal.signal(signal.SIGTERM, self._request_stop)

        rp = requests.get('http://httpbin.org/get')
        self.origin_ip = rp.json().get('origin', '')
        logger.info("[*] Current Ip Address: %s" % self.origin_ip)

        self.geoip_reader = geoip2.database.Reader(os.path.join(self.base_dir, 'data/GeoLite2-Country.mmdb'))

    def load_input_proxies(self):
        # 2. 加载 input proxies 列表
        logger.info("[*] Load input proxies")
        with open(self.filepath) as fd:
            for line in fd:
                self.input_proxies.append(json.loads(line))

    def validate_input_proxies(self):
        # 3. 验证 input proxies 列表
        logger.info("[*] Validate input proxies")
        valid_proxies = self._validate_proxy_list(self.input_proxies)
        self.valid_proxies.extend(valid_proxies)
        logger.info("[*] Check %s input proxies, Got %s valid input proxies" %
                    (len(self.proxies_hash), len(self.valid_proxies)))

    def load_plugins(self):
        # 4. 加载 plugin
        logger.info("[*] Load plugins")
        for plugin_name in os.listdir(os.path.join(self.base_dir, 'plugin')):
            if not plugin_name.endswith('.py') or plugin_name == '__init__.py':
                continue

            try:
                cls = load_object("getproxy.plugin.%s.Proxy" % os.path.splitext(plugin_name)[0])
            except Exception as e:
                logger.info("[-] Load Plugin %s error: %s" % (plugin_name, str(e)))
                continue

            inst = cls()
            inst.proxies = self.valid_proxies.copy()
            self.plugins.append(inst)

    def grab_web_proxies(self):
        # 5. 抓取 web proxies 列表
        logger.info("[*] Grab proxies")

        for plugin in self.plugins:
            self.pool.spawn(plugin.start)

        self.pool.join(timeout=8 * 60)
        self.pool.kill()

        for plugin in self.plugins:
            if not plugin.result:
                continue

            self.web_proxies.extend(plugin.result)

    def validate_web_proxies(self):
        # 6. 验证 web proxies 列表
        logger.info("[*] Validate web proxies")
        input_proxies_len = len(self.proxies_hash)

        valid_proxies = self._validate_proxy_list(self.web_proxies)
        self.valid_proxies.extend(valid_proxies)

        output_proxies_len = len(self.proxies_hash) - input_proxies_len

        logger.info("[*] Check %s output proxies, Got %s valid output proxies" %
                    (output_proxies_len, len(valid_proxies)))
        logger.info("[*] Check %s proxies, Got %s valid proxies" %
                    (len(self.proxies_hash), len(self.valid_proxies)))

    def save_proxies_to_file(self):
        # 7. 保存当前所有已验证的 proxies 列表
        if not self.valid_proxies:
            return

        logger.info("[*] Save valid proxies to file")
        with open(self.filepath, 'w') as fd:
            for item in self.valid_proxies:
                fd.write("%s\n" % json.dumps(item))

    def save_proxies_to_redis(self):
        if not self.valid_proxies:
            return

        logger.info("[*] Save valid proxies to redis")
        self.client.delete(self.set_key)
        for item in self.valid_proxies:
            self.client.sadd(self.set_key, item.get('hash'))

    def start(self):
        self.init()
        self.load_input_proxies()
        self.validate_input_proxies()
        self.load_plugins()
        self.grab_web_proxies()
        self.validate_web_proxies()
        self.save_proxies_to_file()
        self.save_proxies_to_redis()


if __name__ == '__main__':
    g = GetProxy("set:proxies", "redis://127.0.0.1:6379", 0)
    g.start()
