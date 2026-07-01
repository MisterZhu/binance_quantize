# Add Trade Review Skill

## Goal

Create a project-scoped Codex skill that helps AI analyze the local SQLite trading database.

## Scope

- Add `.codex/skills/trade-review/SKILL.md`.
- Add deterministic export script for `trade_journal` and `trade_events`.
- Add database cleanup script with dry-run default and backup support.
- Document how to analyze and clean old data.

## Acceptance

- Skill explains when to use it and what queries/exports to run.
- Export script writes JSONL, CSV, and Markdown summary files.
- Cleanup script can preview deletions and delete old rows only with `--confirm`.
