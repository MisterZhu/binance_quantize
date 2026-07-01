from __future__ import annotations

from pathlib import Path

from loguru import logger

from core.utils.config import PROJECT_ROOT


def setup_logger() -> None:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.remove()
    logger.add(log_dir / "trader.log", rotation="10 MB", retention="14 days", level="INFO")
    logger.add(lambda msg: print(msg, end=""), level="INFO")
