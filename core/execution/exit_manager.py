from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.strategy.indicators import add_emas, ohlcv_to_df
from core.strategy.support_resistance import analyze_levels


@dataclass
class ExitPlan:
    """退出计划，记录初始止损、分批止盈目标和移动止损规则。"""

    stop_loss: float
    partial_targets: list[dict[str, float]]
    exit_rules: dict[str, Any]


def build_exit_plan(config: dict[str, Any], direction: str, entry: float, stop: float) -> ExitPlan:
    exit_config = config.get("exit", {})
    risk = abs(entry - stop)
    partial_config = exit_config.get("partial_take_profit", {})
    targets: list[dict[str, float]] = []
    if partial_config.get("enabled", False) and risk > 0:
        for level in partial_config.get("levels", []):
            r_value = float(level.get("r", 0))
            percent = float(level.get("percent", 0))
            if r_value <= 0 or percent <= 0:
                continue
            price = entry + risk * r_value if direction == "long" else entry - risk * r_value
            targets.append({"r": r_value, "percent": percent, "price": round(price, 8)})
        runner_percent = float(partial_config.get("runner_percent", 0))
        if runner_percent > 0:
            targets.append({"r": 999, "percent": runner_percent, "price": 0})
    return ExitPlan(stop_loss=stop, partial_targets=targets, exit_rules=exit_config)


def trailing_stop_price(config: dict[str, Any], direction: str, entry: float, stop: float, current_price: float) -> float:
    trailing = config.get("exit", {}).get("trailing_stop", {})
    if not trailing.get("enabled", False):
        return stop
    if trailing.get("method", "r_multiple") != "r_multiple":
        return stop
    risk = abs(entry - stop)
    if risk <= 0:
        return stop
    profit_r = (current_price - entry) / risk if direction == "long" else (entry - current_price) / risk
    r_config = trailing.get("r_multiple", {})
    breakeven_at_r = float(r_config.get("breakeven_at_r", 2.0))
    trail_step_r = float(r_config.get("trail_step_r", 2.0))
    if profit_r < breakeven_at_r:
        return stop
    locked_steps = int((profit_r - breakeven_at_r) // trail_step_r)
    locked_r = locked_steps * trail_step_r
    if direction == "long":
        return max(stop, entry + risk * locked_r)
    return min(stop, entry - risk * locked_r)


def ema_follow_exit(config: dict[str, Any], direction: str, rows: list[list[float]]) -> bool:
    trailing = config.get("exit", {}).get("trailing_stop", {})
    ema_config = trailing.get("ema", {})
    if not trailing.get("enabled", False) or trailing.get("method") != "ema":
        return False
    period = int(ema_config.get("period", 21))
    df = add_emas(ohlcv_to_df(rows), (period,))
    last = df.iloc[-1]
    if direction == "long":
        return bool(last["close"] < last[f"ema{period}"])
    return bool(last["close"] > last[f"ema{period}"])


def structure_exit(config: dict[str, Any], direction: str, rows: list[list[float]]) -> bool:
    trailing = config.get("exit", {}).get("trailing_stop", {})
    if not trailing.get("enabled", False) or trailing.get("method") not in {"swing", "structure"}:
        return False
    structure_config = trailing.get("swing", {}) if trailing.get("method") == "swing" else trailing.get("structure", {})
    df = ohlcv_to_df(rows)
    levels = analyze_levels(df, int(structure_config.get("window", 2)))
    close = float(df["close"].iloc[-1])
    if direction == "long" and levels.support is not None:
        return close < levels.support
    if direction == "short" and levels.resistance is not None:
        return close > levels.resistance
    return False
