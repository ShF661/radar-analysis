from __future__ import annotations

import json
import shutil
import subprocess
from typing import Optional


def fetch_klines_5m(cli: str, chain: str, address: str, from_ts: int, to_ts: int) -> list[dict]:
    """Call gmgn-cli market kline --resolution 5m and return the candle list."""
    exe = shutil.which(cli) or cli
    proc = subprocess.run(
        [
            exe, "market", "kline",
            "--chain", chain,
            "--address", address,
            "--resolution", "5m",
            "--from", str(from_ts),
            "--to", str(to_ts),
            "--raw",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gmgn-cli kline failed: {proc.stderr.strip()[:200]}")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("gmgn-cli kline empty output")
    raw = json.loads(out)
    if isinstance(raw, dict) and "data" in raw:
        raw = raw["data"]
    if isinstance(raw, dict):
        raw = raw.get("list") or raw.get("candles") or raw.get("klines") or []
    return raw if isinstance(raw, list) else []


def detect_flash_crash(
    cli: str,
    chain: str,
    address: str,
    push_ts: int,
    threshold: float = -0.80,
) -> tuple[bool, Optional[float], Optional[int]]:
    """
    Pull 288 5m candles covering [push_ts, push_ts+86400].
    Returns (detected, max_drop_pct, crash_ts).
    drop_pct is (low - open) / open; a value ≤ threshold means flash crash.
    """
    try:
        candles = fetch_klines_5m(cli, chain, address, push_ts, push_ts + 86400)
    except Exception:
        return False, None, None

    worst_drop: Optional[float] = None
    worst_ts: Optional[int] = None

    for c in candles:
        try:
            open_p  = float(c.get("open") or c.get("o") or 0)
            low_p   = float(c.get("low")  or c.get("l") or 0)
            ts_raw  = int(c.get("time")   or c.get("t") or 0)
            # gmgn may return millisecond timestamps; normalize to seconds
            ts      = ts_raw // 1000 if ts_raw > 10_000_000_000 else ts_raw
        except (TypeError, ValueError):
            continue
        if open_p <= 0:
            continue
        drop = (low_p - open_p) / open_p
        if worst_drop is None or drop < worst_drop:
            worst_drop = drop
            worst_ts = ts

    if worst_drop is not None and worst_drop <= threshold:
        return True, round(worst_drop * 100, 4), worst_ts
    return False, (round(worst_drop * 100, 4) if worst_drop is not None else None), None
