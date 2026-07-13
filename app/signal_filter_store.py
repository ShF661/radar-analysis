"""Persistent storage for the operator-configurable signal filter config.

Config is stored as JSON at DATA_DIR/signal_filter_config.json (beside radar.db).
Reads and writes are thread-safe via a module-level lock.

Default config (no metric rules, high_tax_threshold at 10%):
{
  "metric_filter_enabled": false,
  "metric_rules": [],
  "high_tax_threshold": 0.10
}
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


_DEFAULT_CONFIG: dict[str, Any] = {
    "metric_filter_enabled": False,
    "metric_rules": [],
    "high_tax_threshold": 0.10,
}

_lock = threading.RLock()


def _config_path(db_path: str) -> Path:
    return Path(db_path).with_name("signal_filter_config.json")


def load_config(db_path: str) -> dict[str, Any]:
    path = _config_path(db_path)
    with _lock:
        if not path.exists():
            return dict(_DEFAULT_CONFIG)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return dict(_DEFAULT_CONFIG)
        # backfill missing keys so callers can always assume presence
        out = dict(_DEFAULT_CONFIG)
        out.update(raw)
        return out


def save_config(db_path: str, config: dict[str, Any]) -> dict[str, Any]:
    path = _config_path(db_path)
    tmp  = path.with_suffix(".json.tmp")
    with _lock:
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        # atomic replace (safe on both POSIX and Windows)
        last_err: Exception | None = None
        import time
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return config
            except PermissionError as e:
                last_err = e
                time.sleep(0.05 * (attempt + 1))
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise last_err if last_err else RuntimeError("save_config: unknown failure")
