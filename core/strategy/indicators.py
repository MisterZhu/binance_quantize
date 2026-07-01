from __future__ import annotations

import pandas as pd


def ohlcv_to_df(rows: list[list[float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def add_emas(df: pd.DataFrame, periods: tuple[int, ...]) -> pd.DataFrame:
    out = df.copy()
    for period in periods:
        out[f"ema{period}"] = out["close"].ewm(span=period, adjust=False).mean()
    return out


def ema_slope_up(df: pd.DataFrame, column: str, bars: int = 3) -> bool:
    if len(df) <= bars:
        return False
    return bool(df[column].iloc[-1] > df[column].iloc[-1 - bars])


def volume_expanded(df: pd.DataFrame, window: int, multiplier: float) -> bool:
    if len(df) <= window:
        return False
    avg = df["volume"].iloc[-window - 1 : -1].mean()
    return bool(avg > 0 and df["volume"].iloc[-1] > avg * multiplier)
