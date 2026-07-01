from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from core.utils.config import PROJECT_ROOT


def mask_key(value: str) -> str:
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def signed_account_check(config: dict[str, Any]) -> dict[str, Any]:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    if not api_key or not api_secret:
        return {
            "ok": False,
            "status": "missing_env",
            "message": "BINANCE_API_KEY 或 BINANCE_API_SECRET 未配置",
            "api_key": mask_key(api_key),
        }

    proxy_config = config["exchange"].get("proxy", {})
    proxy_url = proxy_config.get("url") if proxy_config.get("enabled") else None
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    market_type = config["exchange"].get("market_type", "spot")
    if market_type == "futures":
        base_url = "https://fapi.binance.com"
        path = "/fapi/v2/account"
    else:
        base_url = "https://api.binance.com"
        path = "/api/v3/account"

    params = {"timestamp": int(time.time() * 1000), "recvWindow": 10000}
    query = urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{base_url}{path}?{query}&signature={signature}"
    try:
        resp = requests.get(url, headers={"X-MBX-APIKEY": api_key}, proxies=proxies, timeout=15)
    except Exception as exc:
        return {
            "ok": False,
            "status": "network_error",
            "message": str(exc),
            "api_key": mask_key(api_key),
            "proxy": proxy_url or "direct",
        }

    payload: Any
    try:
        payload = resp.json()
    except ValueError:
        payload = resp.text[:500]

    return {
        "ok": resp.status_code == 200,
        "status_code": resp.status_code,
        "status": "ok" if resp.status_code == 200 else "binance_error",
        "message": payload,
        "api_key": mask_key(api_key),
        "proxy": proxy_url or "direct",
        "used_weight_1m": resp.headers.get("x-mbx-used-weight-1m"),
    }
