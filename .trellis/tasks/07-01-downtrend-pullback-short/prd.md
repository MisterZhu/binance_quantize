# Add Strategy Families

## Goal

Organize strategies into families and add the first implementation of:

- Trend breakout family
- Trend pullback family
- Intraday mean reversion family

## Scope

- Add `strategy.family` and `strategy.direction_mode` to built-in strategy configs.
- Group strategy selection by family in the UI.
- Show family-specific entry condition switches.
- Keep existing trend breakout behavior intact.
- Add pullback long/short logic.
- Add VWAP/ATR intraday mean reversion long/short logic.
- Update functional, technical, and requirements docs.
- Document future strategy auto-selection as a roadmap item.

## Non-Goals

- Do not enable automatic strategy selection in this task.
- Do not implement full backtesting or optimization.
- Do not use WebSocket order/event data.

## Acceptance

- Existing three trend breakout strategies still work.
- Pullback and mean reversion strategies appear under their own family.
- Entry condition switches change when the selected strategy family changes.
- Python code compiles.
