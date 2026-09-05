"""YAML configuration loading, validation and atomic persistence."""

from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "strategy.yaml"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "strategy.yaml.example"

DEFAULT_CONFIG: dict[str, Any] = {
    "strategy": {
        "box_model": "asymmetric",
        "history_years": 10,
        "core_quantile": 0.60,
        "quantile": 0.80,
        "timeframe": "weekly",
        "range_pad": 0.02,
        "dte_min": 15,
        "dte_max": 60,
        "expiry_count": 2,
        "min_yield": 0.01,
        "max_wing_steps": 6,
        "symbols": ["510050", "510300"],
    },
    "server": {"host": "127.0.0.1", "port": 8765},
    "dingtalk": {"webhook": "", "access_token": "", "secret": ""},
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def validate_strategy_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return normalized strategy settings or raise ValueError."""
    out = copy.deepcopy(DEFAULT_CONFIG["strategy"])
    out.update(params or {})
    out["quantile"] = float(out["quantile"])
    out["core_quantile"] = float(out["core_quantile"])
    out["range_pad"] = float(out["range_pad"])
    out["min_yield"] = float(out["min_yield"])
    out.pop("max_yield", None)
    out["dte_min"] = int(out["dte_min"])
    out["dte_max"] = int(out["dte_max"])
    out["expiry_count"] = int(out["expiry_count"])
    out["max_wing_steps"] = int(out["max_wing_steps"])
    out["history_years"] = int(out["history_years"])
    if out["box_model"] not in ("baseline", "asymmetric"):
        raise ValueError("box_model must be baseline or asymmetric")
    if not 5 <= out["history_years"] <= 15:
        raise ValueError("history_years must be between 5 and 15")
    if not 0.55 <= out["core_quantile"] <= 0.70:
        raise ValueError("core_quantile must be between 0.55 and 0.70")
    if not 0.80 <= out["quantile"] <= 0.99:
        raise ValueError("quantile must be between 0.80 and 0.99")
    if out["core_quantile"] >= out["quantile"]:
        raise ValueError("core_quantile must be below quantile")
    if out["timeframe"] not in ("daily", "weekly"):
        raise ValueError("timeframe must be daily or weekly")
    if not 0.0 <= out["range_pad"] <= 0.05:
        raise ValueError("range_pad must be between 0.00 and 0.05")
    if out["dte_min"] < 14 or out["dte_max"] > 61 or out["dte_min"] >= out["dte_max"]:
        raise ValueError("DTE window must satisfy 14 <= min < max <= 61")
    if out["expiry_count"] != 2:
        raise ValueError("expiry_count must be 2")
    if not 0.01 <= out["min_yield"] <= 0.03:
        raise ValueError("min_yield must be between 0.01 and 0.03 (monthly)")
    if not 1 <= out["max_wing_steps"] <= 12:
        raise ValueError("max_wing_steps must be between 1 and 12")
    symbols = out.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [x.strip() for x in symbols.split(",") if x.strip()]
    if not symbols or any(x not in ("510050", "510300") for x in symbols):
        raise ValueError("symbols may only contain 510050 and 510300")
    out["symbols"] = symbols
    return out


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = _merge(DEFAULT_CONFIG, config or {})
    merged["strategy"] = validate_strategy_params(merged.get("strategy") or {})
    server = merged["server"]
    server["host"] = str(server.get("host") or "127.0.0.1")
    server["port"] = int(server.get("port") or 8765)
    if not 1 <= server["port"] <= 65535:
        raise ValueError("server.port must be between 1 and 65535")
    for key in ("webhook", "access_token", "secret"):
        merged["dingtalk"][key] = str(merged["dingtalk"].get(key) or "")
    return merged


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    path = Path(path)
    source = path if path.exists() else EXAMPLE_CONFIG_PATH
    if not source.exists():
        return validate_config(DEFAULT_CONFIG)
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("YAML root must be a mapping")
    return validate_config(payload)


def save_config(config: dict[str, Any], path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Validate then atomically save YAML."""
    path = Path(path)
    normalized = validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(normalized, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return normalized
