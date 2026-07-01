from __future__ import annotations

import time
from typing import Any

from core.exchange.client import BinanceClient
from core.execution.exit_manager import build_exit_plan
from core.storage.database import Database


class OrderManager:
    """开仓执行器，负责入场成交、保护止损、分批止盈和交易记录。"""

    def __init__(self, config: dict[str, Any], client: BinanceClient, db: Database) -> None:
        self.config = config
        self.client = client
        self.db = db

    def _protective_stop_side(self, direction: str) -> str:
        return "sell" if direction == "long" else "buy"

    def _close_side(self, direction: str) -> str:
        return "sell" if direction == "long" else "buy"

    def _filled_amount(self, order: dict[str, Any], fallback_amount: float) -> float:
        filled = order.get("filled")
        if filled is None and order.get("status") in {"closed", "dry_run"}:
            filled = order.get("amount")
        return float(filled or fallback_amount)

    def _wait_for_entry_fill(self, order: dict[str, Any], symbol: str, requested_amount: float) -> tuple[dict[str, Any], float]:
        if self.config["exchange"]["trade_mode"] != "live":
            return order, requested_amount
        stop_config = self.config.get("execution", {}).get("protective_stop", {})
        order_id = order.get("id")
        if not order_id:
            raise RuntimeError("entry order has no exchange order id")
        timeout = int(stop_config.get("wait_entry_fill_seconds", 20))
        deadline = time.time() + timeout
        latest = order
        while time.time() <= deadline:
            latest = self.client.fetch_order(order_id, symbol)
            filled = self._filled_amount(latest, 0)
            if latest.get("status") == "closed" and filled > 0:
                return latest, filled
            time.sleep(1)
        filled = self._filled_amount(latest, 0)
        if filled > 0:
            return latest, filled
        if stop_config.get("cancel_unfilled_entry", True):
            self.client.cancel_order(order_id, symbol)
            self.db.insert_risk_event(
                "warning",
                "entry_not_filled_canceled",
                "entry order was not filled before protective stop timeout and was canceled",
                {"symbol": symbol, "order_id": order_id, "timeout_seconds": timeout},
            )
        raise RuntimeError("entry order not filled; protective stop was not placed")

    def _create_protective_stop(self, signal: dict[str, Any], amount: float) -> dict[str, Any] | None:
        stop_config = self.config.get("execution", {}).get("protective_stop", {})
        if not stop_config.get("enabled", True):
            return None
        symbol = signal["symbol"]
        market_type = signal["market_type"]
        direction = signal["direction"]
        stop_price = self.client.price_to_precision(symbol, float(signal["stop_loss"]))
        precise_amount = self.client.amount_to_precision(symbol, amount)
        side = self._protective_stop_side(direction)

        if market_type == "futures":
            order_type = "STOP_MARKET"
            params = {"stopPrice": stop_price, "reduceOnly": True, "workingType": "MARK_PRICE"}
            price = None
        else:
            order_type = "STOP_LOSS_LIMIT"
            if direction != "long":
                raise RuntimeError("spot protective stop only supports long positions")
            offset = float(stop_config.get("spot_limit_offset_pct", 0.08)) / 100
            limit_price = self.client.price_to_precision(symbol, stop_price * (1 - offset))
            params = {"stopPrice": stop_price, "timeInForce": "GTC"}
            price = limit_price

        raw = self.client.create_order(symbol, side, order_type, precise_amount, price, params)
        record = {
            "symbol": symbol,
            "market_type": market_type,
            "side": side,
            "order_type": order_type,
            "amount": precise_amount,
            "price": price,
            "status": raw.get("status", "submitted"),
            "exchange_order_id": raw.get("id"),
            "raw": {"protective_stop": raw, "stop_price": stop_price},
        }
        self.db.insert_order(record)
        return record

    def _create_partial_take_profit_orders(
        self,
        signal: dict[str, Any],
        filled_amount: float,
        exit_plan: Any,
    ) -> list[dict[str, Any]]:
        if signal["market_type"] != "futures":
            return []
        side = self._close_side(signal["direction"])
        orders: list[dict[str, Any]] = []
        for target in exit_plan.partial_targets:
            if float(target.get("r", 0)) >= 999:
                continue
            percent = float(target.get("percent", 0))
            if percent <= 0:
                continue
            amount = self.client.amount_to_precision(signal["symbol"], filled_amount * percent / 100)
            price = self.client.price_to_precision(signal["symbol"], float(target["price"]))
            params = {"reduceOnly": True, "timeInForce": "GTC"}
            raw = self.client.create_order(signal["symbol"], side, "limit", amount, price, params)
            record = {
                "symbol": signal["symbol"],
                "market_type": signal["market_type"],
                "side": side,
                "order_type": "limit_take_profit",
                "amount": amount,
                "price": price,
                "status": raw.get("status", "submitted"),
                "exchange_order_id": raw.get("id"),
                "raw": {"partial_take_profit": raw, "target": target},
            }
            self.db.insert_order(record)
            orders.append(record)
        return orders

    def execute_signal(self, signal: dict[str, Any], amount: float) -> dict[str, Any]:
        market_type = signal["market_type"]
        direction = signal["direction"]
        # Spot trading is temporarily closed at the product level. The spot
        # implementation remains in place for future reuse, but live automation
        # should route through futures only.
        if market_type == "spot" and not self.config.get("exchange", {}).get("spot_trading_enabled", False):
            raise RuntimeError("spot trading is disabled; use futures market_type")
        params: dict[str, Any] = {}
        if direction == "long":
            side = "buy"
        elif direction == "short":
            side = "sell"
        else:
            raise ValueError("cannot execute empty signal")

        if market_type == "futures":
            params.update({"reduceOnly": False})

        order_type = self.config["execution"]["order_type"]
        price = None
        if order_type == "limit":
            price = float(signal["entry_price"])

        raw = self.client.create_order(signal["symbol"], side, order_type, amount, price, params)
        self.db.insert_trade_event(
            "entry_submitted",
            signal["symbol"],
            price=price,
            amount=amount,
            message="entry order submitted",
            details={"signal": signal, "order": raw},
        )
        exit_plan = build_exit_plan(self.config, direction, float(signal["entry_price"]), float(signal["stop_loss"]))
        entry_order = raw
        protective_stop: dict[str, Any] | None = None
        try:
            entry_order, filled_amount = self._wait_for_entry_fill(raw, signal["symbol"], amount)
            self.db.insert_trade_event(
                "entry_filled",
                signal["symbol"],
                price=float(signal["entry_price"]),
                amount=filled_amount,
                message="entry order filled",
                details={"entry_order": entry_order},
            )
            protective_stop = self._create_protective_stop(signal, filled_amount)
            self.db.insert_trade_event(
                "protective_stop_placed",
                signal["symbol"],
                price=float(signal["stop_loss"]),
                amount=filled_amount,
                message="protective stop placed",
                details={"protective_stop": protective_stop},
            )
            partial_orders = self._create_partial_take_profit_orders(signal, filled_amount, exit_plan)
            for partial_order in partial_orders:
                self.db.insert_trade_event(
                    "partial_take_profit_placed",
                    signal["symbol"],
                    price=float(partial_order["price"]) if partial_order.get("price") is not None else None,
                    amount=float(partial_order["amount"]),
                    message="partial take profit placed",
                    details=partial_order,
                )
        except Exception as exc:
            self.db.insert_risk_event(
                "critical",
                "protective_stop_failed",
                f"failed to create protective stop: {exc}",
                {"symbol": signal["symbol"], "direction": direction, "stop_loss": signal.get("stop_loss")},
            )
            if self.config.get("execution", {}).get("protective_stop", {}).get("required", True):
                raise
        else:
            partial_state = {
                "orders": partial_orders,
                "filled_targets": [],
            }
            active_strategy = self.config.get("active_strategy", {})
            strategy = self.config.get("strategy", {})
            trade_id = self.db.create_trade_journal(
                {
                    "status": "open",
                    "symbol": signal["symbol"],
                    "market_type": market_type,
                    "direction": direction,
                    "strategy_id": active_strategy.get("id"),
                    "strategy_name": active_strategy.get("name"),
                    "strategy_family": strategy.get("family"),
                    "direction_mode": strategy.get("direction_mode"),
                    "amount": filled_amount,
                    "remaining_amount": filled_amount,
                    "entry_price": float(signal["entry_price"]),
                    "initial_stop": float(signal["stop_loss"]),
                    "final_stop": float(signal["stop_loss"]),
                    "signal_details": signal.get("details", {}),
                    "exit_plan": exit_plan.__dict__,
                    "partial_state": partial_state,
                    "market_context": {
                        "score": signal.get("score"),
                        "rr": signal.get("rr"),
                        "take_profit": signal.get("take_profit"),
                    },
                    "raw": {"entry_order": entry_order, "protective_stop": protective_stop, "partial_orders": partial_orders},
                }
            )
            self.db.insert_trade_event(
                "journal_opened",
                signal["symbol"],
                trade_id=trade_id,
                price=float(signal["entry_price"]),
                amount=filled_amount,
                message="trade journal opened",
                details={"strategy": active_strategy, "family": strategy.get("family")},
            )
            self.db.insert_trade_event(
                "entry_filled",
                signal["symbol"],
                trade_id=trade_id,
                price=float(signal["entry_price"]),
                amount=filled_amount,
                message="entry order filled",
                details={"entry_order": entry_order},
            )
            self.db.insert_trade_event(
                "protective_stop_placed",
                signal["symbol"],
                trade_id=trade_id,
                price=float(signal["stop_loss"]),
                amount=filled_amount,
                message="protective stop placed",
                details={"protective_stop": protective_stop},
            )
            for partial_order in partial_orders:
                self.db.insert_trade_event(
                    "partial_take_profit_placed",
                    signal["symbol"],
                    trade_id=trade_id,
                    price=float(partial_order["price"]) if partial_order.get("price") is not None else None,
                    amount=float(partial_order["amount"]),
                    message="partial take profit placed",
                    details=partial_order,
                )
            self.db.upsert_active_position(
                {
                    "status": "open",
                    "symbol": signal["symbol"],
                    "market_type": market_type,
                    "direction": direction,
                    "amount": filled_amount,
                    "remaining_amount": filled_amount,
                    "entry_price": float(signal["entry_price"]),
                    "stop_loss": float(signal["stop_loss"]),
                    "current_stop": float(signal["stop_loss"]),
                    "entry_order_id": raw.get("id"),
                    "stop_order_id": protective_stop.get("exchange_order_id") if protective_stop else None,
                    "exit_plan": exit_plan.__dict__,
                    "partial_state": partial_state,
                    "raw": {"trade_id": trade_id, "entry_order": entry_order, "protective_stop": protective_stop},
                }
            )
        record = {
            "symbol": signal["symbol"],
            "market_type": market_type,
            "side": side,
            "order_type": order_type,
            "amount": amount,
            "price": price,
            "status": entry_order.get("status", raw.get("status", "submitted")),
            "exchange_order_id": raw.get("id"),
            "raw": {"order": entry_order, "exit_plan": exit_plan.__dict__, "protective_stop": protective_stop},
        }
        self.db.insert_order(record)
        return record
