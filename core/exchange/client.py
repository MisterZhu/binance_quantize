from __future__ import annotations

import os
import time
from typing import Any

import ccxt
from dotenv import load_dotenv
from loguru import logger


class BinanceClient:
    def __init__(self, config: dict[str, Any]) -> None:
        load_dotenv()
        self.config = config
        self.market_type = config["exchange"]["market_type"]
        self.trade_mode = config["exchange"]["trade_mode"]
        self.exchange = self._build_exchange()
        self.markets_loaded = False

    def _build_exchange(self) -> ccxt.Exchange:
        api_key = os.getenv("BINANCE_API_KEY", "")
        secret = os.getenv("BINANCE_API_SECRET", "")
        if self.trade_mode == "live" and (not api_key or not secret):
            raise RuntimeError("live mode requires BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        options: dict[str, Any] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {
                "defaultType": "future" if self.market_type == "futures" else "spot",
                # Market data should stay public. With API keys present, ccxt may try
                # extra Binance currency/permission endpoints during load_markets.
                "fetchCurrencies": False,
            },
        }
        proxy_config = self.config["exchange"].get("proxy", {})
        if proxy_config.get("enabled") and proxy_config.get("url"):
            proxy_url = proxy_config["url"]
            options["proxies"] = {"http": proxy_url, "https": proxy_url}
        exchange = ccxt.binance(options)
        if self.config["exchange"].get("sandbox", False):
            exchange.set_sandbox_mode(True)
        return exchange

    def load_markets(self) -> None:
        if not self.markets_loaded:
            self.exchange.load_markets()
            self.markets_loaded = True

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 250) -> list[list[float]]:
        self.load_markets()
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_balance(self) -> dict[str, Any]:
        self.load_markets()
        return self.exchange.fetch_balance()

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        self.load_markets()
        return self.exchange.fetch_open_orders(symbol)

    def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        self.load_markets()
        return self.exchange.fetch_order(order_id, symbol)

    def cancel_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        self.load_markets()
        if self.trade_mode != "live":
            return {"id": order_id, "symbol": symbol, "status": "canceled", "dry_run": True}
        return self.exchange.cancel_order(order_id, symbol)

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        self.load_markets()
        if not self.exchange.has.get("fetchPositions"):
            return []
        return self.exchange.fetch_positions(symbols)

    def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.load_markets()
        params = params or {}
        if self.trade_mode != "live":
            logger.info("dry_run order: {} {} {} amount={} price={}", symbol, side, order_type, amount, price)
            return {
                "id": f"dry-{int(time.time() * 1000)}",
                "status": "dry_run",
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "amount": amount,
                "price": price,
                "params": params,
            }
        if os.getenv("ENABLE_LIVE_TRADING", "").lower() != "true":
            raise RuntimeError("live order blocked: set ENABLE_LIVE_TRADING=true in .env to allow real orders")
        return self.exchange.create_order(symbol, order_type, side, amount, price, params)

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        self.load_markets()
        return float(self.exchange.amount_to_precision(symbol, amount))

    def price_to_precision(self, symbol: str, price: float) -> float:
        self.load_markets()
        return float(self.exchange.price_to_precision(symbol, price))

    def set_futures_safety(self) -> None:
        if self.market_type != "futures":
            return
        futures_config = self.config.get("futures", {})
        if not futures_config.get("enabled", False):
            raise RuntimeError("futures market selected but futures.enabled is false")
        leverage = int(futures_config.get("leverage", 1))
        if leverage > int(futures_config.get("max_leverage", leverage)):
            raise RuntimeError("configured leverage exceeds max_leverage")
        self.load_markets()
        for symbol in self.config.get("symbols", []):
            try:
                margin_mode = futures_config.get("margin_mode", "isolated")
                self.exchange.set_margin_mode(margin_mode, symbol)
                self.exchange.set_leverage(leverage, symbol)
            except Exception as exc:
                logger.warning("failed to apply futures safety for {}: {}", symbol, exc)
