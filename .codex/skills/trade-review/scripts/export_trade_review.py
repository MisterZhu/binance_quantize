from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB = PROJECT_ROOT / "data" / "trader.sqlite"
DEFAULT_OUT = PROJECT_ROOT / "data" / "exports" / "trade_review"
sys.path.insert(0, str(PROJECT_ROOT))

from core.storage.database import Database  # noqa: E402


def parse_json(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def load_trades(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    trades = rows(conn, "select * from trade_journal order by id desc limit ?", (limit,))
    trades.reverse()
    for trade in trades:
        for key in ("signal_details", "exit_plan", "partial_state", "market_context", "raw"):
            trade[key] = parse_json(trade.get(key))
        events = rows(conn, "select * from trade_events where trade_id = ? order by id asc", (trade["id"],))
        for event in events:
            event["details"] = parse_json(event.get("details"))
        trade["events"] = events
    return trades


def write_jsonl(path: Path, trades: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for trade in trades:
            fh.write(json.dumps(trade, ensure_ascii=False, default=str) + "\n")


def write_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "id",
        "status",
        "symbol",
        "direction",
        "strategy_name",
        "strategy_family",
        "opened_at",
        "closed_at",
        "entry_price",
        "avg_exit_price",
        "realized_pnl",
        "r_multiple",
        "result",
        "exit_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({field: trade.get(field) for field in fields})


def group_stats(trades: list[dict[str, Any]], key: str) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get(key) or "unknown")].append(trade)
    stats = {}
    for name, items in grouped.items():
        pnl = sum(float(item.get("realized_pnl") or 0) for item in items)
        wins = sum(1 for item in items if item.get("result") == "win")
        losses = sum(1 for item in items if item.get("result") == "loss")
        r_values = [float(item["r_multiple"]) for item in items if item.get("r_multiple") is not None]
        stats[name] = {
            "count": len(items),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(items) if items else 0,
            "pnl": pnl,
            "avg_r": sum(r_values) / len(r_values) if r_values else 0,
        }
    return stats


def write_report(path: Path, trades: list[dict[str, Any]]) -> None:
    total = len(trades)
    closed = [trade for trade in trades if trade.get("status") == "closed"]
    wins = sum(1 for trade in closed if trade.get("result") == "win")
    losses = sum(1 for trade in closed if trade.get("result") == "loss")
    pnl = sum(float(trade.get("realized_pnl") or 0) for trade in closed)
    r_values = [float(trade["r_multiple"]) for trade in closed if trade.get("r_multiple") is not None]

    lines = [
        "# Trade Review Report",
        "",
        f"- Total exported trades: {total}",
        f"- Closed trades: {len(closed)}",
        f"- Wins: {wins}",
        f"- Losses: {losses}",
        f"- Win rate: {(wins / len(closed) * 100) if closed else 0:.2f}%",
        f"- Total estimated PnL: {pnl:.4f}",
        f"- Average R: {(sum(r_values) / len(r_values)) if r_values else 0:.4f}",
        "",
        "## By Strategy Family",
        "",
    ]
    for name, stat in group_stats(closed, "strategy_family").items():
        lines.append(f"- {name}: count={stat['count']}, win_rate={stat['win_rate'] * 100:.2f}%, pnl={stat['pnl']:.4f}, avg_r={stat['avg_r']:.4f}")
    lines.extend(["", "## By Strategy", ""])
    for name, stat in group_stats(closed, "strategy_name").items():
        lines.append(f"- {name}: count={stat['count']}, win_rate={stat['win_rate'] * 100:.2f}%, pnl={stat['pnl']:.4f}, avg_r={stat['avg_r']:.4f}")
    lines.extend(["", "## Data Quality Notes", "", "- PnL may be estimated until exact fill and fee reconciliation is implemented."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")
    Database(db_path).init()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        trades = load_trades(conn, args.limit)

    write_jsonl(out_dir / "trade_review_latest.jsonl", trades)
    write_csv(out_dir / "trade_stats_latest.csv", trades)
    write_report(out_dir / "trade_review_report.md", trades)
    print(f"exported {len(trades)} trades to {out_dir}")


if __name__ == "__main__":
    main()
