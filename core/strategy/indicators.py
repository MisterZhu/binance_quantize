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


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    typical = (out["high"] + out["low"] + out["close"]) / 3
    volume_sum = out["volume"].cumsum()
    out["vwap"] = (typical * out["volume"]).cumsum() / volume_sum.where(volume_sum != 0, 1)
    return out


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    prev_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out[f"atr{period}"] = true_range.rolling(period).mean()
    return out


def add_bollinger(df: pd.DataFrame, period: int = 20, stddev: float = 2.0) -> pd.DataFrame:
    out = df.copy()
    mid = out["close"].rolling(period).mean()
    spread = out["close"].rolling(period).std()
    out["bb_mid"] = mid
    out["bb_upper"] = mid + spread * stddev
    out["bb_lower"] = mid - spread * stddev
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


def near_level(price: float, level: float | None, tolerance_pct: float) -> bool:
    if level is None or level == 0:
        return False
    return abs(price - level) / level <= tolerance_pct
