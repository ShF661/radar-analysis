from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Optional

from evolution.kline import detect_flash_crash


def _parse_push_ts(push_time: str) -> Optional[int]:
    try:
        dt = datetime.fromisoformat(push_time.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return None


def run_tag(
    case: dict,
    cli: str,
    narrative_hit: Optional[int] = None,
    gain_24h_pct: Optional[float] = None,
) -> dict:
    """
    Run all 4 tagging rules for a single case.
    narrative_hit: 1=hit, 0=miss, None=unknown (pre-fetched by scheduler)
    gain_24h_pct: settlement gain % (pre-fetched by scheduler)
    Returns a dict of update fields for evo_db.update_tagging().
    """
    chain     = case.get("chain", "")
    address   = case.get("token_address", "")
    push_time = case.get("push_time", "")

    # Use pre-fetched values, fall back to stored values if not provided
    nh = narrative_hit if narrative_hit is not None else case.get("narrative_hit")
    g  = gain_24h_pct  if gain_24h_pct  is not None else case.get("gain_24h_pct")

    # ── Branch A: flash crash (skip if already detected by flash_scanner) ────
    flash_result: dict = {}
    already_checked = case.get("flash_crash_detected") is not None

    def _branch_a():
        push_ts = _parse_push_ts(push_time)
        if push_ts is None:
            flash_result["flash_crash_detected"] = None
            return
        detected, max_drop, crash_ts = detect_flash_crash(cli, chain, address, push_ts)
        flash_result["flash_crash_detected"] = 1 if detected else 0
        flash_result["flash_crash_max_drop"]  = max_drop
        if crash_ts:
            flash_result["flash_crash_time"] = datetime.fromtimestamp(
                crash_ts, tz=timezone.utc
            ).isoformat()

    if already_checked:
        flash_result["flash_crash_detected"] = case["flash_crash_detected"]
        flash_result["flash_crash_max_drop"]  = case.get("flash_crash_max_drop")
        flash_result["flash_crash_time"]      = case.get("flash_crash_time")
        t = None
    else:
        t = threading.Thread(target=_branch_a, daemon=True)
        t.start()

    # ── Branch B: rule-based tags ─────────────────────────────────────────────
    tags: list[str] = []

    if nh == 0:
        tags.append("grade_mismatch")

    if _has_security_risk(case):
        tags.append("security_risk")

    if g is not None and g < 50:
        tags.append("low_gain")

    # ── Wait for branch A (only if we spawned it) ─────────────────────────────
    if t is not None:
        t.join(timeout=70)

    if flash_result.get("flash_crash_detected") == 1:
        tags.append("flash_crash")

    # ── Build update dict ─────────────────────────────────────────────────────
    updates: dict = {}
    updates.update(flash_result)

    if narrative_hit is not None:
        updates["narrative_hit"] = narrative_hit
    if gain_24h_pct is not None:
        updates["gain_24h_pct"] = gain_24h_pct

    updates["tags"]            = json.dumps(tags)
    updates["is_failure_case"] = 1 if tags else 0
    updates["analyzed_at"]     = datetime.now(timezone.utc).isoformat()
    updates["analysis_status"] = "skipped" if not tags else "done"

    return updates


def _has_security_risk(case: dict) -> bool:
    if case.get("is_honeypot") in ("yes", 1, True):
        return True
    rug = case.get("rug_ratio")
    if rug is not None and rug > 0.3:
        return True
    buy_tax = case.get("buy_tax")
    if buy_tax is not None and buy_tax > 10:
        return True
    sell_tax = case.get("sell_tax")
    if sell_tax is not None and sell_tax > 10:
        return True
    return False
