#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals, absolute_import, division, print_function

import logging
import retrying
import requests
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)


class Proxy(object):
    def __init__(self):
        self.url = "http://www.cool-proxy.net/proxies.json"
        self.user_agent = UserAgent()

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

        proxies_list = resp.json()
        return [{"host": proxy.get("ip"), "port": proxy.get("port"), "from": "cool"} for proxy in proxies_list]

    def start(self):
        proxies_list = self.extract_proxy(self.url)
        self.result.extend(proxies_list)


if __name__ == '__main__':
    p = Proxy()
    p.start()

    for i in p.result:
        print(i)

    print(len(p.result))
