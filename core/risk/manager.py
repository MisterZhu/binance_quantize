from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.storage.database import Database


@dataclass
class RiskDecision:
    """风控决策结果，包含是否允许开仓和最终下单数量。"""

    allowed: bool
    reason: str
    amount: float = 0.0


class RiskManager:
    """下单前硬性风控，负责过滤信号并按止损距离计算仓位。"""

    def __init__(self, config: dict[str, Any], db: Database) -> None:
        self.config = config
        self.db = db

    def evaluate(self, signal: dict[str, Any], equity_usdt: float) -> RiskDecision:
        if signal["direction"] == "none":
            return RiskDecision(False, "no actionable signal")
        if self.db.get_state("bot_status", "paused") != "running":
            return RiskDecision(False, "bot is not running")
        if self.db.get_active_position():
            return RiskDecision(False, "active position exists")
        # Spot execution is intentionally disabled for now. We keep spot market
        # data and code paths available, but automatic trading should use
        # USD-M futures only until the product decision changes.
        if signal["market_type"] == "spot" and not self.config.get("exchange", {}).get("spot_trading_enabled", False):
            return RiskDecision(False, "spot trading disabled")
        if self.config["risk"].get("require_stop_loss", True) and not signal.get("stop_loss"):
            return RiskDecision(False, "missing stop loss")
        if signal.get("rr") is None or signal["rr"] < float(self.config["strategy"]["min_rr"]):
            return RiskDecision(False, "rr below minimum")

        entry = float(signal["entry_price"])
        stop = float(signal["stop_loss"])
        risk_per_unit = abs(entry - stop)
        if risk_per_unit <= 0:
            return RiskDecision(False, "invalid stop distance")

        risk_budget = equity_usdt * float(self.config["risk"]["risk_per_trade_pct"]) / 100
        raw_amount = risk_budget / risk_per_unit
        max_notional = float(self.config["risk"]["max_position_usdt"])
        if signal["market_type"] == "futures":
            if not self.config.get("futures", {}).get("enabled", False):
                return RiskDecision(False, "futures disabled")
            if signal["direction"] == "short" and not self.config.get("futures", {}).get("allow_short", False):
                return RiskDecision(False, "short disabled")
            leverage = int(self.config.get("futures", {}).get("leverage", 1))
            max_leverage = int(self.config.get("futures", {}).get("max_leverage", 1))
            if leverage > max_leverage:
                return RiskDecision(False, "leverage exceeds max_leverage")
            max_notional = min(max_notional, float(self.config["futures"]["max_notional_usdt"]))
        amount = min(raw_amount, max_notional / entry)
        if amount <= 0:
            return RiskDecision(False, "amount too small")
        return RiskDecision(True, "allowed", amount=amount)
