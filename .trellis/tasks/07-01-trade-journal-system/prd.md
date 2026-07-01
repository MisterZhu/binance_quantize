# Add Trade Journal System

## Goal

Persist a complete trade lifecycle journal that can later be analyzed by AI to understand why trades won or lost.

## Scope

- Add `trade_journal` and `trade_events` SQLite tables.
- Record signal, entry, protective stop, partial take profit, trailing stop, and exit events.
- Bind journals to strategy id/name/family/direction mode.
- Store entry checklist, exit plan, raw orders, and market context.
- Create a first-pass close summary when an active position disappears or a market exit is submitted.
- Show journal and event tables in the Streamlit UI.
- Update docs.

## Non-Goals

- Do not implement complete exchange fill reconciliation in this task.
- Do not calculate exact fees unless available in order payloads.
- Do not add AI review generation yet; store fields that make AI review possible later.

## Acceptance

- New live/dry-run entries create a trade journal record.
- Order lifecycle actions create trade events.
- Closed positions update journal status and estimated PnL/R multiple.
- UI exposes recent trade journals and events.
