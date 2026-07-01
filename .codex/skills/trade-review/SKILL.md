---
name: trade-review
description: Analyze this project's Binance Quantize SQLite trading database, export trade_journal/trade_events for AI review, summarize strategy performance, diagnose wins/losses, and safely clean old trading data. Use when the user asks to review trades, analyze profitability, inspect strategy results, export trading logs, or delete/archive old SQLite trading records.
---

# Trade Review

Use this skill for Binance Quantize trade review tasks.

## Data Source

Default database:

```text
data/trader.sqlite
```

Important tables:

- `trade_journal`: one row per managed trade, with strategy, entry/exit, estimated PnL, R multiple, result, exit reason, signal details, exit plan, and raw data.
- `trade_events`: lifecycle events for each trade, such as entry fill, protective stop, partial take profit, trailing stop update, and close.
- `signals`: strategy signals and checklist details.
- `orders`: order records and raw exchange payloads.
- `risk_events`: risk and runtime errors.

## Standard Workflow

1. Export review data first:

```bash
.venv/bin/python .codex/skills/trade-review/scripts/export_trade_review.py --limit 100
```

2. Read generated files under:

```text
data/exports/trade_review/
```

3. Prefer `trade_review_latest.jsonl` for structured AI analysis and `trade_review_report.md` for a quick human-readable summary.

4. Analyze at minimum:

- total trades
- win/loss/breakeven counts
- total and average PnL
- average R multiple
- results grouped by `strategy_family`, `strategy_name`, `symbol`, `direction`, and `exit_reason`
- recurring loss patterns from `signal_details` and event sequences

5. Call out data quality limitations. Current journal PnL may be estimated until exact exchange fill/fee reconciliation is implemented.

## Cleanup Workflow

Never delete data without a dry run first.

Preview deletion:

```bash
.venv/bin/python scripts/cleanup_trading_data.py --older-than-days 90
```

Delete after confirming:

```bash
.venv/bin/python scripts/cleanup_trading_data.py --older-than-days 90 --backup --confirm
```

Clear all generated trading records only when explicitly requested:

```bash
.venv/bin/python scripts/cleanup_trading_data.py --all --backup --confirm
```

Do not delete `.env`, config files, strategies, or source code.

## Review Output Style

For user-facing summaries:

- Start with direct findings.
- Separate strategy performance, risk/exit behavior, and data quality issues.
- Suggest concrete strategy adjustments only when supported by the data.
- Mention if sample size is too small.
