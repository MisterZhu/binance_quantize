# Add Market Regime Filter

## Goal

Add a first-pass market regime filter before the existing EMA structure entry logic.

The filter should help avoid confusing mixed conditions:

- Higher timeframe downtrend with noisy intraday bounces.
- Higher timeframe uptrend with noisy intraday pullbacks.
- Range-like conditions where both long and short trend entries should be treated more carefully.

## Scope

- Add configurable strategy parameters for market regime filtering.
- Evaluate regime from the existing trend timeframe candles.
- Gate long/short signals before final direction selection.
- Store regime details in signal `details`.
- Show basic parameters in the strategy UI.
- Keep the current trend breakout strategy intact.

## Non-Goals

- Do not implement a complete VWAP/ATR mean-reversion strategy in this task.
- Do not add WebSocket data.
- Do not change live order execution.

## Acceptance

- Default strategy can enable the filter.
- In downtrend mode, long entries are blocked unless countertrend entries are explicitly allowed.
- In uptrend mode, short entries are blocked unless countertrend entries are explicitly allowed.
- Range mode can optionally block new trend entries.
- Existing strategy signals still include checklist details.
