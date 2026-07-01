from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import pandas as pd

from core.strategy.indicators import add_emas, ema_slope_up, ohlcv_to_df, volume_expanded
from core.strategy.support_resistance import (
    analyze_levels,
    breakdown_below,
    breakout_above,
    first_pullback_holds_long,
    first_pullback_rejects_short,
    has_profit_space_long,
    has_profit_space_short,
)


@dataclass
class Signal:
    symbol: str
    market_type: str
    direction: str
    score: float
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    rr: float | None
    details: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class EmaStructureStrategy:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        strategy = config["strategy"]
        self.ema_fast = int(strategy["ema_fast"])
        self.ema_mid = int(strategy["ema_mid"])
        self.ema_slow = int(strategy["ema_slow"])
        self.min_rr = float(strategy["min_rr"])
        self.volume_window = int(strategy["volume_window"])
        self.volume_multiplier = float(strategy["volume_multiplier"])
        self.structure_lookback = int(strategy["structure_lookback"])
        self.swing_window = int(strategy.get("swing_window", 2))
        self.breakout_lookback = int(strategy.get("breakout_lookback", 6))
        self.pullback_lookback = int(strategy.get("pullback_lookback", 8))
        self.level_tolerance_pct = float(strategy.get("level_tolerance_pct", 0.15)) / 100
        self.min_check_score = float(strategy.get("min_check_score", 0.85))
        self.market_regime = strategy.get("market_regime", {})
        self.enabled_long_checks = strategy.get("enabled_long_checks", {})
        self.enabled_short_checks = strategy.get("enabled_short_checks", {})
        self.stop_loss_pct = float(config["execution"]["stop_loss_pct"]) / 100
        self.take_profit_pct = float(config["execution"]["take_profit_pct"]) / 100

    def prepare(self, rows: list[list[float]]) -> pd.DataFrame:
        return add_emas(ohlcv_to_df(rows), (self.ema_fast, self.ema_mid, self.ema_slow))

    def classify_regime(self, last_trend: pd.Series, structure: str, ema_mid_up: bool) -> dict[str, Any]:
        enabled = bool(self.market_regime.get("enabled", True))
        price_above_slow = bool(last_trend["close"] > last_trend[f"ema{self.ema_slow}"])
        price_below_slow = bool(last_trend["close"] < last_trend[f"ema{self.ema_slow}"])
        require_structure = bool(self.market_regime.get("require_structure_alignment", True))
        up_structure_ok = structure == "up" or not require_structure
        down_structure_ok = structure == "down" or not require_structure

        if price_above_slow and ema_mid_up and up_structure_ok:
            regime = "uptrend"
        elif price_below_slow and not ema_mid_up and down_structure_ok:
            regime = "downtrend"
        elif structure == "range":
            regime = "range"
        else:
            regime = "mixed"

        block_countertrend = bool(self.market_regime.get("block_countertrend", True))
        block_range_entries = bool(self.market_regime.get("block_range_entries", False))
        allow_long = True
        allow_short = True
        if enabled and block_countertrend:
            if regime == "downtrend":
                allow_long = False
            elif regime == "uptrend":
                allow_short = False
        if enabled and block_range_entries and regime in {"range", "mixed"}:
            allow_long = False
            allow_short = False

        return {
            "enabled": enabled,
            "regime": regime,
            "allow_long": allow_long,
            "allow_short": allow_short,
            "price_above_ema200": price_above_slow,
            "price_below_ema200": price_below_slow,
            "ema21_up": ema_mid_up,
            "structure": structure,
            "block_countertrend": block_countertrend,
            "block_range_entries": block_range_entries,
            "require_structure_alignment": require_structure,
        }

    def analyze(
        self,
        symbol: str,
        market_type: str,
        trend_rows: list[list[float]],
        confirm_rows: list[list[float]],
        entry_rows: list[list[float]],
    ) -> Signal:
        trend = self.prepare(trend_rows)
        confirm = self.prepare(confirm_rows)
        entry = self.prepare(entry_rows)
        last_trend = trend.iloc[-1]
        last_confirm = confirm.iloc[-1]
        last_entry = entry.iloc[-1]
        trend_levels = analyze_levels(trend, self.swing_window, max(12, self.structure_lookback * 2))
        entry_levels = analyze_levels(entry, self.swing_window, max(12, self.structure_lookback * 2))
        structure = trend_levels.structure
        trend_ema_mid_up = ema_slope_up(trend, f"ema{self.ema_mid}")
        regime = self.classify_regime(last_trend, structure, trend_ema_mid_up)
        price = float(last_entry["close"])
        long_stop = float(entry_levels.support or price * (1 - self.stop_loss_pct))
        short_stop = float(entry_levels.resistance or price * (1 + self.stop_loss_pct))
        long_take = float(trend_levels.resistance or price * (1 + self.take_profit_pct))
        short_take = float(trend_levels.support or price * (1 - self.take_profit_pct))
        long_rr = (long_take - price) / (price - long_stop) if price > long_stop else 0
        short_rr = (price - short_take) / (short_stop - price) if short_stop > price else 0

        long_checks = {
            "1h_price_above_ema200": bool(last_trend["close"] > last_trend[f"ema{self.ema_slow}"]),
            "1h_ema21_up": trend_ema_mid_up,
            "1h_hh_hl_structure": structure == "up",
            "1h_profit_space_to_resistance": has_profit_space_long(price, long_stop, trend_levels.resistance, self.min_rr),
            "15m_ema9_above_ema21": bool(last_confirm[f"ema{self.ema_fast}"] > last_confirm[f"ema{self.ema_mid}"]),
            "15m_ema21_up": ema_slope_up(confirm, f"ema{self.ema_mid}"),
            "15m_volume_expanded": volume_expanded(confirm, self.volume_window, self.volume_multiplier),
            "5m_breakout_resistance": breakout_above(entry, entry_levels.resistance, self.breakout_lookback),
            "5m_first_pullback_holds": first_pullback_holds_long(entry, entry_levels.resistance, self.level_tolerance_pct, self.pullback_lookback),
            "combined_stop_less_than_half_target": bool(long_rr >= self.min_rr),
        }
        short_checks = {
            "1h_price_below_ema200": bool(last_trend["close"] < last_trend[f"ema{self.ema_slow}"]),
            "1h_ema21_down": not trend_ema_mid_up,
            "1h_ll_lh_structure": structure == "down",
            "1h_profit_space_to_support": has_profit_space_short(price, short_stop, trend_levels.support, self.min_rr),
            "15m_ema9_below_ema21": bool(last_confirm[f"ema{self.ema_fast}"] < last_confirm[f"ema{self.ema_mid}"]),
            "15m_ema21_down": not ema_slope_up(confirm, f"ema{self.ema_mid}"),
            "15m_volume_expanded": volume_expanded(confirm, self.volume_window, self.volume_multiplier),
            "5m_breakdown_support": breakdown_below(entry, entry_levels.support, self.breakout_lookback),
            "5m_pullback_rejects_support_as_resistance": first_pullback_rejects_short(entry, entry_levels.support, self.level_tolerance_pct, self.pullback_lookback),
            "combined_stop_less_than_half_target": bool(short_rr >= self.min_rr),
        }

        allow_short = market_type == "futures" and bool(self.config.get("futures", {}).get("allow_short", False))
        active_long_checks = {k: v for k, v in long_checks.items() if self.enabled_long_checks.get(k, True)}
        active_short_checks = {k: v for k, v in short_checks.items() if self.enabled_short_checks.get(k, True)}
        long_score = sum(bool(v) for v in active_long_checks.values()) / max(len(active_long_checks), 1)
        short_score = sum(bool(v) for v in active_short_checks.values()) / max(len(active_short_checks), 1) if allow_short else 0
        if not regime["allow_long"]:
            long_score = 0
        if not regime["allow_short"]:
            short_score = 0

        if long_score >= short_score:
            direction = "long" if long_score >= self.min_check_score else "none"
            score = long_score
        else:
            direction = "short" if short_score >= self.min_check_score else "none"
            score = short_score

        if direction == "long":
            stop = long_stop
            take = long_take
            rr = long_rr
        elif direction == "short":
            stop = short_stop
            take = short_take
            rr = short_rr
        else:
            stop = take = rr = None

        if rr is not None and rr < self.min_rr:
            direction = "none"

        return Signal(
            symbol=symbol,
            market_type=market_type,
            direction=direction,
            score=round(float(score), 4),
            entry_price=price if direction != "none" else None,
            stop_loss=round(float(stop), 8) if stop else None,
            take_profit=round(float(take), 8) if take else None,
            rr=round(float(rr), 4) if rr else None,
            details={
                "structure": structure,
                "market_regime": regime,
                "trend_support": trend_levels.support,
                "trend_resistance": trend_levels.resistance,
                "entry_support": entry_levels.support,
                "entry_resistance": entry_levels.resistance,
                "long_rr_candidate": round(float(long_rr), 4),
                "short_rr_candidate": round(float(short_rr), 4),
                "long_checks": long_checks,
                "short_checks": short_checks,
                "active_long_checks": active_long_checks,
                "active_short_checks": active_short_checks,
                "latest_close": price,
            },
        )
