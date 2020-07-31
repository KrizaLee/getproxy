# -*- coding: utf-8 -*-

import click
from getproxy import GetProxy


@click.command()
@click.option('--key', default="set:proxies", type=str,
              help='Specify the key name in redis that stores the verified proxies.')
@click.option('--url', default="redis://127.0.0.1:6379", type=str,
              help='Specify the full Redis URL for connecting.')
@click.option('--db', default=0, type=int,
              help='Specify the db in redis that stores the verified proxies.')
def main(key, url, db):
    g = GetProxy(key, url, db)
    g.start()


if __name__ == "__main__":
    main()
