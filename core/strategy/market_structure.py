from __future__ import annotations

import pandas as pd


def detect_structure(df: pd.DataFrame, lookback: int = 5) -> str:
    if len(df) < lookback * 2 + 2:
        return "unknown"
    recent = df.iloc[-lookback:]
    previous = df.iloc[-lookback * 2 : -lookback]
    recent_high = recent["high"].max()
    recent_low = recent["low"].min()
    previous_high = previous["high"].max()
    previous_low = previous["low"].min()
    if recent_high > previous_high and recent_low > previous_low:
        return "up"
    if recent_high < previous_high and recent_low < previous_low:
        return "down"
    return "range"
