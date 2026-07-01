from __future__ import annotations

import argparse
import time

from loguru import logger

from core.exchange.client import BinanceClient
from core.execution.order_manager import OrderManager
from core.execution.position_manager import PositionManager
from core.risk.manager import RiskManager
from core.storage.database import Database
from core.strategy.ema_structure import EmaStructureStrategy
from core.utils.config import load_config
from core.utils.logger import setup_logger


def estimate_equity_usdt(balance: dict) -> float:
    total = balance.get("total", {})
    if "USDT" in total and total["USDT"]:
        return float(total["USDT"])
    return 100.0


def run_once() -> None:
    setup_logger()
    config = load_config()
    db = Database()
    db.init()
    db.set_state("last_error", "")
    client = BinanceClient(config)
    if config["exchange"]["market_type"] == "futures":
        client.set_futures_safety()
    strategy = EmaStructureStrategy(config)
    risk = RiskManager(config, db)
    orders = OrderManager(config, client, db)
    positions = PositionManager(config, client, db)

    if positions.manage_active_position():
        logger.info("managed active position; skip new entries")
        return

    timeframes = config["strategy"]["timeframes"]
    for symbol in config["symbols"]:
        logger.info("analyzing {}", symbol)
        trend = client.fetch_ohlcv(symbol, timeframes["trend"], limit=260)
        confirm = client.fetch_ohlcv(symbol, timeframes["confirm"], limit=260)
        entry = client.fetch_ohlcv(symbol, timeframes["entry"], limit=260)
        signal = strategy.analyze(symbol, config["exchange"]["market_type"], trend, confirm, entry).to_record()
        db.insert_signal(signal)
        logger.info("signal {} {} score={} rr={}", symbol, signal["direction"], signal["score"], signal["rr"])

        balance = client.fetch_balance() if config["exchange"]["trade_mode"] == "live" else {"total": {"USDT": 100.0}}
        decision = risk.evaluate(signal, estimate_equity_usdt(balance))
        if not decision.allowed:
            logger.info("risk rejected {}: {}", symbol, decision.reason)
            continue
        order = orders.execute_signal(signal, decision.amount)
        logger.info("order submitted {}", order)


def loop(interval: int) -> None:
    db = Database()
    db.init()
    db.set_state("bot_status", "running")
    while db.get_state("bot_status", "paused") == "running":
        try:
            run_once()
        except Exception as exc:
            logger.exception("bot loop error: {}", exc)
            db.insert_risk_event("error", "bot_loop_error", str(exc))
            db.set_state("last_error", str(exc))
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run one analysis cycle")
    parser.add_argument("--interval", type=int, default=60, help="loop interval seconds")
    args = parser.parse_args()
    if args.once:
        db = Database()
        db.init()
        try:
            run_once()
        except Exception as exc:
            logger.exception("single run error: {}", exc)
            db.insert_risk_event("error", "single_run_error", str(exc))
            db.set_state("last_error", str(exc))
            raise
    else:
        loop(args.interval)


if __name__ == "__main__":
    main()
