from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class StructureLevels:
    structure: str
    swing_highs: list[float]
    swing_lows: list[float]
    resistance: float | None
    support: float | None


def find_swings(df: pd.DataFrame, window: int = 2, limit: int = 12) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    if len(df) < window * 2 + 1:
        return highs, lows
    for idx in range(window, len(df) - window):
        high = float(df["high"].iloc[idx])
        low = float(df["low"].iloc[idx])
        high_slice = df["high"].iloc[idx - window : idx + window + 1]
        low_slice = df["low"].iloc[idx - window : idx + window + 1]
        if high >= float(high_slice.max()):
            highs.append((idx, high))
        if low <= float(low_slice.min()):
            lows.append((idx, low))
    return highs[-limit:], lows[-limit:]


def classify_structure(swing_highs: list[tuple[int, float]], swing_lows: list[tuple[int, float]]) -> str:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "unknown"
    prev_high, last_high = swing_highs[-2][1], swing_highs[-1][1]
    prev_low, last_low = swing_lows[-2][1], swing_lows[-1][1]
    if last_high > prev_high and last_low > prev_low:
        return "up"
    if last_high < prev_high and last_low < prev_low:
        return "down"
    return "range"


def nearest_resistance(price: float, swing_highs: list[tuple[int, float]]) -> float | None:
    levels = sorted({level for _, level in swing_highs if level > price})
    return levels[0] if levels else None


def nearest_support(price: float, swing_lows: list[tuple[int, float]]) -> float | None:
    levels = sorted({level for _, level in swing_lows if level < price}, reverse=True)
    return levels[0] if levels else None


def analyze_levels(df: pd.DataFrame, swing_window: int = 2, limit: int = 12) -> StructureLevels:
    swing_highs, swing_lows = find_swings(df, swing_window, limit)
    price = float(df["close"].iloc[-1])
    return StructureLevels(
        structure=classify_structure(swing_highs, swing_lows),
        swing_highs=[level for _, level in swing_highs],
        swing_lows=[level for _, level in swing_lows],
        resistance=nearest_resistance(price, swing_highs),
        support=nearest_support(price, swing_lows),
    )


def has_profit_space_long(price: float, stop: float, resistance: float | None, min_rr: float) -> bool:
    if resistance is None or price <= stop:
        return False
    return (resistance - price) / (price - stop) >= min_rr


def has_profit_space_short(price: float, stop: float, support: float | None, min_rr: float) -> bool:
    if support is None or stop <= price:
        return False
    return (price - support) / (stop - price) >= min_rr


def breakout_above(df: pd.DataFrame, resistance: float | None, lookback: int = 6) -> bool:
    if resistance is None or len(df) < lookback + 1:
        return False
    recent = df.iloc[-lookback:]
    previous = df.iloc[: -lookback]
    if previous.empty:
        return False
    was_below = float(previous["close"].tail(20).max()) <= resistance
    now_above = float(recent["close"].iloc[-1]) > resistance
    return bool(was_below and now_above)


def breakdown_below(df: pd.DataFrame, support: float | None, lookback: int = 6) -> bool:
    if support is None or len(df) < lookback + 1:
        return False
    recent = df.iloc[-lookback:]
    previous = df.iloc[: -lookback]
    if previous.empty:
        return False
    was_above = float(previous["close"].tail(20).min()) >= support
    now_below = float(recent["close"].iloc[-1]) < support
    return bool(was_above and now_below)


def first_pullback_holds_long(df: pd.DataFrame, level: float | None, tolerance_pct: float = 0.0015, lookback: int = 8) -> bool:
    if level is None or len(df) < lookback:
        return False
    recent = df.iloc[-lookback:]
    touched = (recent["low"] <= level * (1 + tolerance_pct)).any()
    closed_above = float(recent["close"].iloc[-1]) > level
    return bool(touched and closed_above)


def first_pullback_rejects_short(df: pd.DataFrame, level: float | None, tolerance_pct: float = 0.0015, lookback: int = 8) -> bool:
    if level is None or len(df) < lookback:
        return False
    recent = df.iloc[-lookback:]
    touched = (recent["high"] >= level * (1 - tolerance_pct)).any()
    closed_below = float(recent["close"].iloc[-1]) < level
    return bool(touched and closed_below)
