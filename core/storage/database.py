from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.utils.config import PROJECT_ROOT


DB_PATH = PROJECT_ROOT / "data" / "trader.sqlite"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


class Database:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists signals (
                    id integer primary key autoincrement,
                    created_at text not null,
                    symbol text not null,
                    market_type text not null,
                    direction text not null,
                    score real not null,
                    entry_price real,
                    stop_loss real,
                    take_profit real,
                    rr real,
                    executed integer not null default 0,
                    details text not null
                );

                create table if not exists orders (
                    id integer primary key autoincrement,
                    created_at text not null,
                    symbol text not null,
                    market_type text not null,
                    side text not null,
                    order_type text not null,
                    amount real not null,
                    price real,
                    status text not null,
                    exchange_order_id text,
                    raw text not null
                );

                create table if not exists trades (
                    id integer primary key autoincrement,
                    opened_at text,
                    closed_at text,
                    symbol text not null,
                    market_type text not null,
                    direction text not null,
                    amount real,
                    entry_price real,
                    exit_price real,
                    fee real default 0,
                    pnl real default 0,
                    r_multiple real,
                    exit_reason text
                );

                create table if not exists risk_events (
                    id integer primary key autoincrement,
                    created_at text not null,
                    level text not null,
                    code text not null,
                    message text not null,
                    details text not null
                );

                create table if not exists bot_state (
                    key text primary key,
                    value text not null,
                    updated_at text not null
                );

                create table if not exists active_positions (
                    id integer primary key autoincrement,
                    created_at text not null,
                    updated_at text not null,
                    status text not null,
                    symbol text not null,
                    market_type text not null,
                    direction text not null,
                    amount real not null,
                    remaining_amount real not null,
                    entry_price real not null,
                    stop_loss real not null,
                    current_stop real not null,
                    entry_order_id text,
                    stop_order_id text,
                    exit_plan text not null,
                    partial_state text not null,
                    raw text not null
                );
                """
            )

    def insert_signal(self, signal: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                insert into signals (
                    created_at, symbol, market_type, direction, score, entry_price,
                    stop_loss, take_profit, rr, executed, details
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    signal["symbol"],
                    signal["market_type"],
                    signal["direction"],
                    signal["score"],
                    signal.get("entry_price"),
                    signal.get("stop_loss"),
                    signal.get("take_profit"),
                    signal.get("rr"),
                    int(signal.get("executed", False)),
                    json.dumps(signal.get("details", {}), ensure_ascii=False, default=json_default),
                ),
            )
            return int(cur.lastrowid)

    def insert_order(self, order: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                insert into orders (
                    created_at, symbol, market_type, side, order_type, amount,
                    price, status, exchange_order_id, raw
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    order["symbol"],
                    order["market_type"],
                    order["side"],
                    order["order_type"],
                    order["amount"],
                    order.get("price"),
                    order["status"],
                    order.get("exchange_order_id"),
                    json.dumps(order.get("raw", {}), ensure_ascii=False, default=json_default),
                ),
            )
            return int(cur.lastrowid)

    def insert_risk_event(self, level: str, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "insert into risk_events (created_at, level, code, message, details) values (?, ?, ?, ?, ?)",
                (utc_now(), level, code, message, json.dumps(details or {}, ensure_ascii=False, default=json_default)),
            )

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into bot_state (key, value, updated_at)
                values (?, ?, ?)
                on conflict(key) do update set value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, utc_now()),
            )

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("select value from bot_state where key = ?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def recent_rows(self, table: str, limit: int = 50) -> list[sqlite3.Row]:
        allowed = {"signals", "orders", "trades", "risk_events", "bot_state", "active_positions"}
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        with self.connect() as conn:
            return list(conn.execute(f"select * from {table} order by rowid desc limit ?", (limit,)).fetchall())

    def get_active_position(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "select * from active_positions where status = 'open' order by id desc limit 1"
            ).fetchone()

    def upsert_active_position(self, position: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                insert into active_positions (
                    created_at, updated_at, status, symbol, market_type, direction,
                    amount, remaining_amount, entry_price, stop_loss, current_stop,
                    entry_order_id, stop_order_id, exit_plan, partial_state, raw
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    utc_now(),
                    position.get("status", "open"),
                    position["symbol"],
                    position["market_type"],
                    position["direction"],
                    position["amount"],
                    position.get("remaining_amount", position["amount"]),
                    position["entry_price"],
                    position["stop_loss"],
                    position.get("current_stop", position["stop_loss"]),
                    position.get("entry_order_id"),
                    position.get("stop_order_id"),
                    json.dumps(position.get("exit_plan", {}), ensure_ascii=False, default=json_default),
                    json.dumps(position.get("partial_state", {}), ensure_ascii=False, default=json_default),
                    json.dumps(position.get("raw", {}), ensure_ascii=False, default=json_default),
                ),
            )
            return int(cur.lastrowid)

    def update_active_position(self, position_id: int, updates: dict[str, Any]) -> None:
        allowed = {
            "status",
            "remaining_amount",
            "current_stop",
            "stop_order_id",
            "partial_state",
            "raw",
        }
        assignments = []
        values: list[Any] = []
        for key, value in updates.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            if key in {"partial_state", "raw"}:
                values.append(json.dumps(value, ensure_ascii=False, default=json_default))
            else:
                values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(position_id)
        with self.connect() as conn:
            conn.execute(f"update active_positions set {', '.join(assignments)} where id = ?", values)
