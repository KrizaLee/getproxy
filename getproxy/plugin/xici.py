#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals, absolute_import, division, print_function

import re
import logging
import retrying
import requests
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)


class Proxy(object):
    def __init__(self):
        self.urls = [
            'https://www.xicidaili.com/nn/',
            'https://www.xicidaili.com/nt/',
            'https://www.xicidaili.com/wn/',
            'https://www.xicidaili.com/wt/',
        ]
        self.user_agent = UserAgent()

        self.re_ip_pattern = re.compile(r'<td>(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})</td>', re.I)
        self.re_port_pattern = re.compile(r'<td>(\d{1,5})</td>', re.I)

        self.proxies = []
        self.result = []

    @property
    def _get_headers(self):
        return {"User-Agent": self.user_agent.random}

    @property
    def _get_proxies(self):
        if self.proxies:
            proxy = self.proxies.pop(0)
            return {proxy['type']: "%s:%s" % (proxy['host'], proxy['port'])}
        else:
            return None

    @retrying.retry(stop_max_attempt_number=5)
    def parse_url(self, url):
        response = requests.get(url, headers=self._get_headers, proxies=self._get_proxies, timeout=10)
        assert response.status_code == 200
        return response

    def extract_proxy(self, url):
        try:
            resp = self.parse_url(url)
        except Exception as e:
            logger.error("[-] Request url {url} error: {error}".format(url=url, error=str(e)))
            return []

        host_list = self.re_ip_pattern.findall(resp.text)
        port_list = self.re_port_pattern.findall(resp.text)
        if not host_list or not port_list:
            logger.warning("[-] Request url {url} is empty.".format(url=url))
            return []
        if len(host_list) != len(port_list):
            logger.warning("[-] Request url {url} len(host) != len(port).".format(url=url))
            return []

        proxies_list = dict(zip(host_list, port_list))
        return [{"host": host, "port": int(port), "from": "xici"} for host, port in proxies_list.items()]

    def start(self):
        for url in self.urls:
            proxies_list = self.extract_proxy(url)
            self.result.extend(proxies_list)


if __name__ == '__main__':
    p = Proxy()
    p.start()

    for i in p.result:
        print(i)

    print(len(p.result))
