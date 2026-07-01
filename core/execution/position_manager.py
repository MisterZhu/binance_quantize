from __future__ import annotations

import json
from typing import Any

from core.exchange.client import BinanceClient
from core.execution.exit_manager import ema_follow_exit, structure_exit, trailing_stop_price
from core.storage.database import Database


class PositionManager:
    def __init__(self, config: dict[str, Any], client: BinanceClient, db: Database) -> None:
        self.config = config
        self.client = client
        self.db = db

    def _close_side(self, direction: str) -> str:
        return "sell" if direction == "long" else "buy"

    def _position_contracts(self, symbol: str, direction: str) -> float:
        positions = self.client.fetch_positions([symbol])
        for item in positions:
            item_symbol = str(item.get("symbol", ""))
            if item_symbol != symbol and not item_symbol.startswith(f"{symbol}:"):
                continue
            contracts = float(item.get("contracts") or 0)
            side = item.get("side")
            if contracts == 0:
                continue
            if direction == "long" and side in {"long", None}:
                return abs(contracts)
            if direction == "short" and side in {"short", None}:
                return abs(contracts)
        return 0.0

    def _last_price(self, symbol: str) -> float:
        ticker = self.client.exchange.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close"))

    def _cancel_stop(self, stop_order_id: str | None, symbol: str) -> None:
        if not stop_order_id:
            return
        try:
            self.client.cancel_order(stop_order_id, symbol)
        except Exception as exc:
            self.db.insert_risk_event("warning", "cancel_stop_failed", str(exc), {"symbol": symbol, "order_id": stop_order_id})

    def _place_stop(self, symbol: str, direction: str, amount: float, stop_price: float) -> dict[str, Any]:
        side = self._close_side(direction)
        precise_amount = self.client.amount_to_precision(symbol, amount)
        precise_stop = self.client.price_to_precision(symbol, stop_price)
        raw = self.client.create_order(
            symbol,
            side,
            "STOP_MARKET",
            precise_amount,
            None,
            {"stopPrice": precise_stop, "reduceOnly": True, "workingType": "MARK_PRICE"},
        )
        record = {
            "symbol": symbol,
            "market_type": "futures",
            "side": side,
            "order_type": "trailing_stop_update",
            "amount": precise_amount,
            "price": None,
            "status": raw.get("status", "submitted"),
            "exchange_order_id": raw.get("id"),
            "raw": {"stop_update": raw, "stop_price": precise_stop},
        }
        self.db.insert_order(record)
        return record

    def _is_better_stop(self, direction: str, current_stop: float, candidate_stop: float) -> bool:
        if direction == "long":
            return candidate_stop > current_stop
        return candidate_stop < current_stop

    def manage_active_position(self) -> bool:
        row = self.db.get_active_position()
        if not row:
            return False
        position_id = int(row["id"])
        symbol = row["symbol"]
        direction = row["direction"]
        entry = float(row["entry_price"])
        initial_stop = float(row["stop_loss"])
        current_stop = float(row["current_stop"])
        remaining = float(row["remaining_amount"])

        exchange_remaining = self._position_contracts(symbol, direction)
        if exchange_remaining <= 0:
            self.db.update_active_position(position_id, {"status": "closed", "remaining_amount": 0})
            self.db.insert_risk_event("info", "position_closed", "active position closed", {"symbol": symbol})
            return True

        if abs(exchange_remaining - remaining) > 0:
            remaining = exchange_remaining
            self.db.update_active_position(position_id, {"remaining_amount": remaining})

        timeframes = self.config["strategy"]["timeframes"]
        entry_rows = self.client.fetch_ohlcv(symbol, timeframes["entry"], limit=120)
        exit_rows = entry_rows
        should_close = ema_follow_exit(self.config, direction, exit_rows) or structure_exit(self.config, direction, exit_rows)
        if should_close:
            side = self._close_side(direction)
            raw = self.client.create_order(symbol, side, "market", self.client.amount_to_precision(symbol, remaining), None, {"reduceOnly": True})
            self.db.insert_order(
                {
                    "symbol": symbol,
                    "market_type": "futures",
                    "side": side,
                    "order_type": "market_exit",
                    "amount": remaining,
                    "price": None,
                    "status": raw.get("status", "submitted"),
                    "exchange_order_id": raw.get("id"),
                    "raw": {"exit": raw, "reason": "trailing_exit_rule"},
                }
            )
            self.db.update_active_position(position_id, {"status": "closing"})
            return True

        current_price = self._last_price(symbol)
        candidate_stop = trailing_stop_price(self.config, direction, entry, initial_stop, current_price)
        if self._is_better_stop(direction, current_stop, candidate_stop):
            self._cancel_stop(row["stop_order_id"], symbol)
            stop_record = self._place_stop(symbol, direction, remaining, candidate_stop)
            raw = json.loads(row["raw"]) if isinstance(row["raw"], str) else {}
            raw["last_stop_update"] = stop_record
            self.db.update_active_position(
                position_id,
                {
                    "current_stop": candidate_stop,
                    "stop_order_id": stop_record.get("exchange_order_id"),
                    "raw": raw,
                },
            )
        return True
