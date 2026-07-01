from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import pandas as pd

from core.strategy.indicators import add_atr, add_bollinger, add_emas, add_vwap, ema_slope_up, near_level, ohlcv_to_df, volume_expanded
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
    """策略信号结果；只表达交易意图，不直接触发下单。"""

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
    """多周期策略引擎，根据策略大类生成 checklist 和候选交易信号。"""

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
        self.enabled_long_checks = strategy.get("enabled_long_checks", {})
        self.enabled_short_checks = strategy.get("enabled_short_checks", {})
        self.stop_loss_pct = float(config["execution"]["stop_loss_pct"]) / 100
        self.take_profit_pct = float(config["execution"]["take_profit_pct"]) / 100
        self.family = str(strategy.get("family", "trend_breakout"))
        self.direction_mode = str(strategy.get("direction_mode", "both"))

    def prepare(self, rows: list[list[float]]) -> pd.DataFrame:
        return add_emas(ohlcv_to_df(rows), (self.ema_fast, self.ema_mid, self.ema_slow))

    def _empty_signal(self, symbol: str, market_type: str, score: float, details: dict[str, Any]) -> Signal:
        return Signal(
            symbol=symbol,
            market_type=market_type,
            direction="none",
            score=round(float(score), 4),
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            rr=None,
            details=details,
        )

    def analyze(
        self,
        symbol: str,
        market_type: str,
        trend_rows: list[list[float]],
        confirm_rows: list[list[float]],
        entry_rows: list[list[float]],
    ) -> Signal:
        if self.family == "trend_pullback":
            return self.analyze_trend_pullback(symbol, market_type, trend_rows, confirm_rows, entry_rows)
        if self.family == "intraday_mean_reversion":
            return self.analyze_intraday_mean_reversion(symbol, market_type, trend_rows, confirm_rows, entry_rows)
        return self.analyze_trend_breakout(symbol, market_type, trend_rows, confirm_rows, entry_rows)

    def analyze_trend_breakout(
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

    def analyze_trend_pullback(
        self,
        symbol: str,
        market_type: str,
        trend_rows: list[list[float]],
        confirm_rows: list[list[float]],
        entry_rows: list[list[float]],
    ) -> Signal:
        trend = self.prepare(trend_rows)
        confirm = add_vwap(self.prepare(confirm_rows))
        entry = self.prepare(entry_rows)
        last_trend = trend.iloc[-1]
        last_confirm = confirm.iloc[-1]
        last_entry = entry.iloc[-1]
        trend_levels = analyze_levels(trend, self.swing_window, max(12, self.structure_lookback * 2))
        confirm_levels = analyze_levels(confirm, self.swing_window, max(12, self.structure_lookback * 2))
        entry_levels = analyze_levels(entry, self.swing_window, max(12, self.structure_lookback * 2))
        structure = trend_levels.structure
        trend_ema_mid_up = ema_slope_up(trend, f"ema{self.ema_mid}")
        confirm_ema_mid_up = ema_slope_up(confirm, f"ema{self.ema_mid}")
        price = float(last_entry["close"])
        tolerance = self.level_tolerance_pct

        long_stop = float(entry_levels.support or confirm_levels.support or price * (1 - self.stop_loss_pct))
        short_stop = float(entry_levels.resistance or confirm_levels.resistance or price * (1 + self.stop_loss_pct))
        long_take = float(confirm_levels.resistance or trend_levels.resistance or price * (1 + self.take_profit_pct))
        short_take = float(confirm_levels.support or trend_levels.support or price * (1 - self.take_profit_pct))
        long_rr = (long_take - price) / (price - long_stop) if price > long_stop else 0
        short_rr = (price - short_take) / (short_stop - price) if short_stop > price else 0

        long_checks = {
            "pullback_long_trend_up": bool(last_trend["close"] > last_trend[f"ema{self.ema_slow}"] and trend_ema_mid_up and structure == "up"),
            "pullback_long_near_support_or_ema": bool(
                near_level(price, float(last_confirm[f"ema{self.ema_mid}"]), tolerance)
                or near_level(price, float(last_confirm[f"ema{self.ema_slow}"]), tolerance)
                or near_level(price, confirm_levels.support, tolerance)
                or near_level(price, float(last_confirm.get("vwap", 0)), tolerance)
            ),
            "pullback_long_entry_reclaims_ema9": bool(last_entry["close"] > last_entry[f"ema{self.ema_fast}"] and last_entry["close"] > last_entry["open"]),
            "pullback_long_confirm_ema21_not_down": confirm_ema_mid_up,
            "pullback_long_rr_ok": bool(long_rr >= self.min_rr),
        }
        short_checks = {
            "pullback_short_trend_down": bool(last_trend["close"] < last_trend[f"ema{self.ema_slow}"] and not trend_ema_mid_up and structure == "down"),
            "pullback_short_near_resistance_or_ema": bool(
                near_level(price, float(last_confirm[f"ema{self.ema_mid}"]), tolerance)
                or near_level(price, float(last_confirm[f"ema{self.ema_slow}"]), tolerance)
                or near_level(price, confirm_levels.resistance, tolerance)
                or near_level(price, float(last_confirm.get("vwap", 0)), tolerance)
            ),
            "pullback_short_entry_loses_ema9": bool(last_entry["close"] < last_entry[f"ema{self.ema_fast}"] and last_entry["close"] < last_entry["open"]),
            "pullback_short_confirm_ema21_not_up": not confirm_ema_mid_up,
            "pullback_short_rr_ok": bool(short_rr >= self.min_rr),
        }

        return self._directional_signal(
            symbol,
            market_type,
            price,
            long_stop,
            long_take,
            long_rr,
            short_stop,
            short_take,
            short_rr,
            long_checks,
            short_checks,
            {
                "family": self.family,
                "structure": structure,
                "trend_support": trend_levels.support,
                "trend_resistance": trend_levels.resistance,
                "confirm_support": confirm_levels.support,
                "confirm_resistance": confirm_levels.resistance,
                "entry_support": entry_levels.support,
                "entry_resistance": entry_levels.resistance,
                "latest_close": price,
            },
        )

    def analyze_intraday_mean_reversion(
        self,
        symbol: str,
        market_type: str,
        trend_rows: list[list[float]],
        confirm_rows: list[list[float]],
        entry_rows: list[list[float]],
    ) -> Signal:
        trend = self.prepare(trend_rows)
        confirm = add_bollinger(add_atr(add_vwap(self.prepare(confirm_rows)), 14), 20, 2.0)
        entry = self.prepare(entry_rows)
        last_trend = trend.iloc[-1]
        last_confirm = confirm.iloc[-1]
        last_entry = entry.iloc[-1]
        entry_levels = analyze_levels(entry, self.swing_window, max(12, self.structure_lookback * 2))
        price = float(last_entry["close"])
        vwap = float(last_confirm.get("vwap", price))
        atr = float(last_confirm.get("atr14") or 0)
        bb_upper = float(last_confirm.get("bb_upper") or price)
        bb_lower = float(last_confirm.get("bb_lower") or price)
        bb_mid = float(last_confirm.get("bb_mid") or vwap)
        atr_pct = atr / price if price else 0
        vwap_deviation = (price - vwap) / vwap if vwap else 0
        min_deviation_pct = float(self.config["strategy"].get("mean_reversion_min_vwap_deviation_pct", 0.6)) / 100
        min_atr_pct = float(self.config["strategy"].get("mean_reversion_min_atr_pct", 0.8)) / 100

        long_stop = float(entry_levels.support or min(bb_lower, price * (1 - self.stop_loss_pct)))
        short_stop = float(entry_levels.resistance or max(bb_upper, price * (1 + self.stop_loss_pct)))
        long_take = float(min(vwap, bb_mid) if min(vwap, bb_mid) > price else price * (1 + self.take_profit_pct))
        short_take = float(max(vwap, bb_mid) if max(vwap, bb_mid) < price else price * (1 - self.take_profit_pct))
        long_rr = (long_take - price) / (price - long_stop) if price > long_stop else 0
        short_rr = (price - short_take) / (short_stop - price) if short_stop > price else 0

        long_checks = {
            "reversion_long_volatility_enough": bool(atr_pct >= min_atr_pct),
            "reversion_long_below_vwap": bool(vwap_deviation <= -min_deviation_pct),
            "reversion_long_near_lower_band": bool(price <= bb_lower or near_level(price, bb_lower, self.level_tolerance_pct)),
            "reversion_long_entry_reversal": bool(last_entry["close"] > last_entry["open"] and last_entry["close"] > last_entry[f"ema{self.ema_fast}"]),
            "reversion_long_target_to_vwap_ok": bool(long_rr >= self.min_rr),
        }
        short_checks = {
            "reversion_short_volatility_enough": bool(atr_pct >= min_atr_pct),
            "reversion_short_above_vwap": bool(vwap_deviation >= min_deviation_pct),
            "reversion_short_near_upper_band": bool(price >= bb_upper or near_level(price, bb_upper, self.level_tolerance_pct)),
            "reversion_short_entry_reversal": bool(last_entry["close"] < last_entry["open"] and last_entry["close"] < last_entry[f"ema{self.ema_fast}"]),
            "reversion_short_target_to_vwap_ok": bool(short_rr >= self.min_rr),
        }

        return self._directional_signal(
            symbol,
            market_type,
            price,
            long_stop,
            long_take,
            long_rr,
            short_stop,
            short_take,
            short_rr,
            long_checks,
            short_checks,
            {
                "family": self.family,
                "trend_close": float(last_trend["close"]),
                "vwap": vwap,
                "atr14": atr,
                "atr_pct": round(float(atr_pct * 100), 4),
                "vwap_deviation_pct": round(float(vwap_deviation * 100), 4),
                "bb_upper": bb_upper,
                "bb_mid": bb_mid,
                "bb_lower": bb_lower,
                "entry_support": entry_levels.support,
                "entry_resistance": entry_levels.resistance,
                "latest_close": price,
            },
        )

    def _directional_signal(
        self,
        symbol: str,
        market_type: str,
        price: float,
        long_stop: float,
        long_take: float,
        long_rr: float,
        short_stop: float,
        short_take: float,
        short_rr: float,
        long_checks: dict[str, bool],
        short_checks: dict[str, bool],
        extra_details: dict[str, Any],
    ) -> Signal:
        allow_short = market_type == "futures" and bool(self.config.get("futures", {}).get("allow_short", False))
        active_long_checks = {k: v for k, v in long_checks.items() if self.enabled_long_checks.get(k, True)}
        active_short_checks = {k: v for k, v in short_checks.items() if self.enabled_short_checks.get(k, True)}
        long_score = sum(bool(v) for v in active_long_checks.values()) / max(len(active_long_checks), 1)
        short_score = sum(bool(v) for v in active_short_checks.values()) / max(len(active_short_checks), 1) if allow_short else 0
        if self.direction_mode == "long_only":
            short_score = 0
        if self.direction_mode == "short_only":
            long_score = 0

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

        details = {
            **extra_details,
            "long_rr_candidate": round(float(long_rr), 4),
            "short_rr_candidate": round(float(short_rr), 4),
            "long_checks": long_checks,
            "short_checks": short_checks,
            "active_long_checks": active_long_checks,
            "active_short_checks": active_short_checks,
        }
        return Signal(
            symbol=symbol,
            market_type=market_type,
            direction=direction,
            score=round(float(score), 4),
            entry_price=price if direction != "none" else None,
            stop_loss=round(float(stop), 8) if stop else None,
            take_profit=round(float(take), 8) if take else None,
            rr=round(float(rr), 4) if rr else None,
            details=details,
        )
