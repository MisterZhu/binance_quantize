from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
STRATEGIES_PATH = PROJECT_ROOT / "strategies.yaml"
RUNTIME_STRATEGY_PATH = PROJECT_ROOT / "data" / "runtime_strategy.yaml"


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    if Path(path) == CONFIG_PATH and STRATEGIES_PATH.exists():
        apply_active_strategy(config, load_strategy_store())
        if RUNTIME_STRATEGY_PATH.exists():
            apply_strategy_params(config, load_yaml(RUNTIME_STRATEGY_PATH))
    return config


def load_yaml(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_config(config: dict[str, Any], path: Path | str = CONFIG_PATH) -> None:
    clean = dict(config)
    clean.pop("active_strategy", None)
    with Path(path).open("w", encoding="utf-8") as fh:
        yaml.safe_dump(clean, fh, allow_unicode=True, sort_keys=False)


def load_strategy_store(path: Path | str = STRATEGIES_PATH) -> dict[str, Any]:
    strategy_path = Path(path)
    if not strategy_path.exists():
        return {"active_strategy": "", "strategies": []}
    with strategy_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {"active_strategy": "", "strategies": []}


def save_strategy_store(store: dict[str, Any], path: Path | str = STRATEGIES_PATH) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        yaml.safe_dump(store, fh, allow_unicode=True, sort_keys=False)


def save_runtime_strategy(params: dict[str, Any], path: Path | str = RUNTIME_STRATEGY_PATH) -> None:
    runtime_path = Path(path)
    runtime_path.parent.mkdir(exist_ok=True)
    with runtime_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(params, fh, allow_unicode=True, sort_keys=False)


def clear_runtime_strategy(path: Path | str = RUNTIME_STRATEGY_PATH) -> None:
    runtime_path = Path(path)
    if runtime_path.exists():
        runtime_path.unlink()


def get_active_strategy(store: dict[str, Any]) -> dict[str, Any] | None:
    active_id = store.get("active_strategy")
    for strategy in store.get("strategies", []):
        if strategy.get("id") == active_id:
            return strategy
    return None


def apply_active_strategy(config: dict[str, Any], store: dict[str, Any]) -> None:
    active = get_active_strategy(store)
    if not active:
        return
    params = active.get("params", {})
    config["active_strategy"] = {
        "id": active.get("id"),
        "name": active.get("name"),
        "builtin": bool(active.get("builtin", False)),
        "description": active.get("description", ""),
    }
    apply_strategy_params(config, params)


def apply_strategy_params(config: dict[str, Any], params: dict[str, Any]) -> None:
    if "strategy" in params:
        config["strategy"] = {**config.get("strategy", {}), **params["strategy"]}
    if "execution" in params:
        config["execution"] = {**config.get("execution", {}), **params["execution"]}
    if "exit" in params:
        config["exit"] = {**config.get("exit", {}), **params["exit"]}


def deep_get(data: dict[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current
