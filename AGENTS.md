<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

Use the `/trellis:start` command when starting a new session to:
- Initialize your developer identity
- Understand current project context
- Read relevant guidelines

Use `@/.trellis/` to learn:
- Development workflow (`workflow.md`)
- Project structure guidelines (`spec/`)
- Developer workspace (`workspace/`)

If you're using Codex, project-scoped helpers may also live in:
- `.agents/skills/` for reusable Trellis skills
- `.codex/agents/` for optional custom subagents

Keep this managed block so 'trellis update' can refresh the instructions.

<!-- TRELLIS:END -->

# Binance Quantize Agent Guide

This file is the first project-level document an AI coding agent should read
when working in this repository. Keep it concise, practical, and synchronized
with the current codebase.

## First Read Order

Read these files before making code changes:

1. `AGENTS.md`
2. `README.md`
3. `.trellis/workflow.md`
4. `.trellis/spec/guides/index.md`
5. `docs/technical_design.md`
6. `docs/requirements_and_design.md`
7. `strategies.yaml`
8. `config.yaml`

For task-specific work, also read the relevant files under `.trellis/spec/`.

## Project Goal

`binance_quantize` is a local Streamlit-based Binance USD-M Futures short-term
trading assistant. The current product direction is futures-first.

The project focuses on:

- Multi-family strategy presets and editable strategy parameters.
- Signal checklist evaluation for trend breakout, trend pullback, and future
  intraday mean-reversion strategies.
- Risk-based position sizing.
- Live Binance API integration.
- Protective stop-loss orders after entry.
- Exit management through partial take profit and trailing stop logic.
- SQLite-based trade journal and AI-assisted trade review.

## Current Product Scope

- Active market type: Binance USD-M Futures.
- Spot code may still exist historically, but UI and configuration should stay
  futures-focused unless the user explicitly asks to restore spot support.
- First priority is capital protection and reviewable execution data, not
  aggressive automation.
- Live trading must always keep protective stop-loss behavior intact.

## Safety Rules

- Never print or commit `.env`, API keys, API secrets, session tokens, or other
  credentials.
- Never remove stop-loss protection from live order flow.
- Never enable live trading or automatic order placement unless the user
  explicitly requests it.
- Never delete SQLite trading records without a dry run first.
- For destructive database cleanup, prefer `--backup --confirm`.
- Do not run cleanup while the bot is managing an active live position unless
  the user explicitly understands the risk.
- Keep generated files out of git: database files, logs, exports, backups,
  caches, and virtual environments.

## Development Workflow

Use Trellis for non-trivial changes:

```bash
python3 ./.trellis/scripts/get_context.py
python3 ./.trellis/scripts/task.py list
python3 ./.trellis/scripts/task.py create "<title>" --slug <slug>
python3 ./.trellis/scripts/task.py start <task-name>
```

Before editing, read the relevant `.trellis/spec/` guidelines. After finishing:

```bash
python3 ./.trellis/scripts/add_session.py --title "<title>" --commit "<hash>"
python3 ./.trellis/scripts/task.py finish
```

Use normal git commits with concise conventional-style messages, for example:

```text
feat: add trade review skill
fix: use configured exit timeframe
docs: update agent guide
```

## AI Code Comment Rules

- 新增代码只在必要处加简洁注释，说明业务意图、特殊分支、兜底、异步时序、异常处理或平台差异；不要写“设置变量”“调用方法”这类重复代码表面行为的注释。
- 修改旧代码或旧业务逻辑时，如果改变了原有判断、流程、参数、默认值、错误处理或兼容逻辑，必须在关键位置写清楚“为什么这样改”，包括对应问题、需求背景或保留旧逻辑的原因。
- Bug 修复、临时兼容、字段不明确、平台限制、后续待清理等场景，需要在注释中说明触发场景和边界；注释优先用中文，保持短句、直白、可维护。

## Common Commands

Start Streamlit UI:

```bash
.venv/bin/streamlit run app.py
```

Run bot loop:

```bash
.venv/bin/python bot_runner.py
```

Check Binance API authentication:

```bash
.venv/bin/python check_auth.py
```

Check network/proxy access:

```bash
.venv/bin/python check_network.py
```

Compile changed Python files when no test suite exists:

```bash
python3 -m py_compile <file1.py> <file2.py>
```

## Project Skills

Use the project-scoped Codex skill `trade-review` when the user asks to:

- Analyze trading results.
- Inspect SQLite trading data.
- Review win/loss reasons.
- Evaluate strategy performance.
- Export trade journal data for AI review.
- Clean or archive old trading records.

Skill path:

```text
.codex/skills/trade-review/SKILL.md
```

Trade review export:

```bash
.venv/bin/python .codex/skills/trade-review/scripts/export_trade_review.py --limit 100
```

SQLite cleanup dry run:

```bash
.venv/bin/python scripts/cleanup_trading_data.py --older-than-days 90
```

SQLite cleanup with backup and confirmation:

```bash
.venv/bin/python scripts/cleanup_trading_data.py --older-than-days 90 --backup --confirm
```

## Important Files

- `app.py`: Streamlit UI and local operator dashboard.
- `bot_runner.py`: automated bot loop.
- `config.yaml`: runtime trading configuration.
- `strategies.yaml`: strategy families, presets, conditions, and exit settings.
- `core/strategy/ema_structure.py`: strategy signal and checklist logic.
- `core/execution/order_manager.py`: exchange order execution.
- `core/execution/exit_manager.py`: exit plan and trailing logic.
- `core/execution/position_manager.py`: position monitoring and exit execution.
- `core/risk/risk_manager.py`: position sizing and risk checks.
- `core/storage/database.py`: SQLite schema and persistence helpers.
- `data/trader.sqlite`: local runtime database, ignored by git.
- `docs/technical_design.md`: technical architecture.
- `docs/requirements_and_design.md`: product requirements and roadmap.
- `docs/functional_spec.md`: user-facing feature details.

## Strategy Families

Current strategy organization:

- `trend_breakout`: trend-following breakout and pullback confirmation.
- `trend_pullback`: shorting rebounds in downtrends or buying pullbacks in
  uptrends.
- `intraday_mean_reversion`: reserved for VWAP/ATR intraday reversion strategy
  development.

When adding or changing strategies, update both `strategies.yaml` and relevant
UI/engine logic. Keep Chinese labels clear because the operator UI is Chinese.

## Database Notes

SQLite is used for local persistence. Main review tables:

- `trade_journal`: one row per managed trade.
- `trade_events`: lifecycle events for each trade.
- `signals`: generated strategy signals.
- `orders`: local order records and exchange payloads.
- `risk_events`: blocked trades, errors, and risk-control messages.

Prefer exporting JSONL/CSV/Markdown through the `trade-review` skill before
asking AI to analyze performance. Do not query or mutate the database with ad
hoc scripts unless the existing scripts are insufficient.

## UI Language

The Streamlit UI is intended for Chinese-language operation. User-facing labels,
strategy names, checklist names, and risk explanations should be Chinese unless
there is a strong technical reason to keep an exchange/API field in English.
