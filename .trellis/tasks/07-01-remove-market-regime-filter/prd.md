# Remove Redundant Market Regime Filter

## Goal

Remove the first-pass market regime filter from the current trend strategy.

The existing entry checklist already includes higher timeframe direction checks:

- Price relative to EMA200
- EMA21 direction
- HH/HL or LL/LH structure
- Profit space to next support/resistance

The extra filter duplicates those checks and makes the UI harder to understand.

## Scope

- Remove market regime gating from strategy execution.
- Remove market regime controls from the strategy UI.
- Remove market regime fields from built-in strategy configs.
- Remove current documentation that claims the filter is implemented.
- Keep the normal long/short checklist display clear.

## Non-Goals

- Do not implement VWAP/ATR mean reversion in this task.
- Do not remove the completed Trellis history task that previously added the filter.

## Acceptance

- Signals are decided only by the existing checklist score and risk checks.
- Strategy UI no longer shows market regime filter controls.
- Built-in strategies no longer include `market_regime`.
- Python files compile.
