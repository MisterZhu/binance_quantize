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
    """SQLite 存储层，统一记录信号、订单、持仓、复盘和风控事件。"""

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

                create table if not exists trade_journal (
                    id integer primary key autoincrement,
                    created_at text not null,
                    updated_at text not null,
                    status text not null,
                    symbol text not null,
                    market_type text not null,
                    direction text not null,
                    strategy_id text,
                    strategy_name text,
                    strategy_family text,
                    direction_mode text,
                    opened_at text,
                    closed_at text,
                    amount real,
                    remaining_amount real,
                    entry_price real,
                    avg_exit_price real,
                    initial_stop real,
                    final_stop real,
                    realized_pnl real default 0,
                    fee real default 0,
                    r_multiple real,
                    result text,
                    exit_reason text,
                    signal_details text not null,
                    exit_plan text not null,
                    partial_state text not null,
                    market_context text not null,
                    raw text not null,
                    ai_review_notes text
                );

                create table if not exists trade_events (
                    id integer primary key autoincrement,
                    created_at text not null,
                    trade_id integer,
                    symbol text not null,
                    event_type text not null,
                    price real,
                    amount real,
                    message text,
                    details text not null
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
        allowed = {"signals", "orders", "trades", "risk_events", "bot_state", "active_positions", "trade_journal", "trade_events"}
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

    def create_trade_journal(self, journal: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                insert into trade_journal (
                    created_at, updated_at, status, symbol, market_type, direction,
                    strategy_id, strategy_name, strategy_family, direction_mode,
                    opened_at, amount, remaining_amount, entry_price, initial_stop,
                    final_stop, signal_details, exit_plan, partial_state, market_context, raw
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    utc_now(),
                    journal.get("status", "open"),
                    journal["symbol"],
                    journal["market_type"],
                    journal["direction"],
                    journal.get("strategy_id"),
                    journal.get("strategy_name"),
                    journal.get("strategy_family"),
                    journal.get("direction_mode"),
                    journal.get("opened_at", utc_now()),
                    journal.get("amount"),
                    journal.get("remaining_amount", journal.get("amount")),
                    journal.get("entry_price"),
                    journal.get("initial_stop"),
                    journal.get("final_stop", journal.get("initial_stop")),
                    json.dumps(journal.get("signal_details", {}), ensure_ascii=False, default=json_default),
                    json.dumps(journal.get("exit_plan", {}), ensure_ascii=False, default=json_default),
                    json.dumps(journal.get("partial_state", {}), ensure_ascii=False, default=json_default),
                    json.dumps(journal.get("market_context", {}), ensure_ascii=False, default=json_default),
                    json.dumps(journal.get("raw", {}), ensure_ascii=False, default=json_default),
                ),
            )
            return int(cur.lastrowid)

    def update_trade_journal(self, trade_id: int, updates: dict[str, Any]) -> None:
        allowed = {
            "status",
            "closed_at",
            "remaining_amount",
            "avg_exit_price",
            "final_stop",
            "realized_pnl",
            "fee",
            "r_multiple",
            "result",
            "exit_reason",
            "partial_state",
            "raw",
            "ai_review_notes",
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
        values.append(trade_id)
        with self.connect() as conn:
            conn.execute(f"update trade_journal set {', '.join(assignments)} where id = ?", values)

    def insert_trade_event(
        self,
        event_type: str,
        symbol: str,
        trade_id: int | None = None,
        price: float | None = None,
        amount: float | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                insert into trade_events (
                    created_at, trade_id, symbol, event_type, price, amount, message, details
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    trade_id,
                    symbol,
                    event_type,
                    price,
                    amount,
                    message,
                    json.dumps(details or {}, ensure_ascii=False, default=json_default),
                ),
            )

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
