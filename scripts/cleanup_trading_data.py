from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "trader.sqlite"
sys.path.insert(0, str(PROJECT_ROOT))

from core.storage.database import Database  # noqa: E402
TABLE_DATE_COLUMNS = {
    "signals": "created_at",
    "orders": "created_at",
    "risk_events": "created_at",
    "active_positions": "created_at",
    "trade_journal": "created_at",
    "trade_events": "created_at",
    "trades": "opened_at",
}


def backup_db(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}-{stamp}.sqlite"
    shutil.copy2(db_path, backup_path)
    return backup_path


def table_count(conn: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    query = f"select count(*) from {table}"
    if where:
        query += f" where {where}"
    return int(conn.execute(query, params).fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--older-than-days", type=int)
    parser.add_argument("--all", action="store_true", help="delete all trading records")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="required to actually delete")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")
    Database(db_path).init()
    if not args.all and args.older_than_days is None:
        raise SystemExit("choose --older-than-days N or --all")

    cutoff = None
    if args.older_than_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.older_than_days)).isoformat()

    with sqlite3.connect(db_path) as conn:
        plan = []
        for table, column in TABLE_DATE_COLUMNS.items():
            if args.all:
                count = table_count(conn, table)
                plan.append((table, "", (), count))
            else:
                where = f"{column} is not null and {column} < ?"
                params = (cutoff,)
                count = table_count(conn, table, where, params)
                plan.append((table, where, params, count))

        print("cleanup plan:")
        for table, _, _, count in plan:
            print(f"- {table}: {count} rows")

        if not args.confirm:
            print("dry run only. Add --confirm to delete.")
            return

        if args.backup:
            backup_path = backup_db(db_path)
            print(f"backup created: {backup_path}")

        for table, where, params, _ in plan:
            if args.all:
                conn.execute(f"delete from {table}")
            else:
                conn.execute(f"delete from {table} where {where}", params)
        conn.commit()
        conn.execute("vacuum")
        print("cleanup complete")


if __name__ == "__main__":
    main()
