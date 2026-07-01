from __future__ import annotations

import sys

import requests

from core.utils.config import load_config


def check(url: str, proxy_url: str | None = None) -> None:
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    label = proxy_url or "direct"
    try:
        resp = requests.get(url, proxies=proxies, timeout=10)
        print(f"{label}: HTTP {resp.status_code} {resp.text[:200]}")
    except Exception as exc:
        print(f"{label}: ERROR {exc}")


def main() -> None:
    config = load_config()
    url = "https://api.binance.com/api/v3/time"
    ip_urls = ["https://api.ipify.org", "https://ifconfig.me/ip"]
    proxy_config = config["exchange"].get("proxy", {})
    check(url)
    if proxy_config.get("url"):
        check(url, proxy_config["url"])
        for ip_url in ip_urls:
            check(ip_url, proxy_config["url"])
    if len(sys.argv) > 1:
        check(url, sys.argv[1])
        for ip_url in ip_urls:
            check(ip_url, sys.argv[1])


if __name__ == "__main__":
    main()
