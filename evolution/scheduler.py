"""
T+24h tagging scheduler — run every 5 minutes via Windows Task Scheduler.

  python -m evolution.scheduler
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Optional

from app.config import load_settings
from app.radar import RadarClient, _hit_to_int
from evolution.db import EvolutionDB
from evolution.tagger import run_tag

_REQUIRED_AI_FIELDS = {
    "root_cause_category", "root_cause_detail",
    "is_prompt_optimizable", "filter_signals", "confidence",
}
_VALID_CATEGORIES = {"narrative_error", "security_risk", "unknown"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


def _load_env() -> None:
    from pathlib import Path
    f = Path(".env")
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        import os
        os.environ.setdefault(k.strip(), v.strip())


def _fetch_t24h(client: RadarClient, case: dict) -> tuple:
    """Returns (narrative_hit, gain_24h_pct). Both may be None on failure."""
    push_record_id = case["push_record_id"]
    chain          = case.get("chain", "")
    address        = case.get("token_address", "")
    pushed_at      = case.get("push_time")

    narrative_hit: Optional[int] = None
    gain_24h_pct: Optional[float] = None

    try:
        task = client.get_task(push_record_id)
        if task:
            score = task.get("latest_score") or {}
            narrative_hit = _hit_to_int(score.get("hit_status"))
    except Exception as e:
        print(f"[scheduler] get_task failed {push_record_id}: {e}", flush=True)

    try:
        bt_raw = client.find_backtest_token(address, chain, pushed_at)
        if bt_raw:
            v = bt_raw.get("settlement_gain_pct")
            gain_24h_pct = float(v) if v is not None else None
    except Exception as e:
        print(f"[scheduler] backtest failed {push_record_id}: {e}", flush=True)

    return narrative_hit, gain_24h_pct


def _build_ai_variables(case: dict, tag_updates: dict) -> dict:
    """Build Langfuse prompt variables for failure_case_analysis."""
    tags = json.loads(tag_updates.get("tags") or "[]")
    return {
        "symbol":          case.get("symbol") or "",
        "chain":           case.get("chain") or "",
        "narrative_grade": case.get("narrative_grade") or "",
        "narrative_text":  case.get("narrative_text") or "",
        "narrative_hit":   "miss" if tag_updates.get("narrative_hit") == 0 else (
                               "hit" if tag_updates.get("narrative_hit") == 1 else "unknown"
                           ),
        "gain_24h_pct":    str(tag_updates.get("gain_24h_pct") or ""),
        "tags":            ", ".join(tags),
        "liquidity":       str(case.get("liquidity") or ""),
        "volume_24h":      str(case.get("volume_24h") or ""),
        "holder_count":    str(case.get("holder_count") or ""),
        "smart_degen_count": str(case.get("smart_degen_count") or ""),
        "renowned_count":  str(case.get("renowned_count") or ""),
        "rug_ratio":       str(case.get("rug_ratio") or ""),
        "is_honeypot":     str(case.get("is_honeypot") or ""),
        "buy_tax":         str(case.get("buy_tax") or ""),
        "sell_tax":        str(case.get("sell_tax") or ""),
    }


def _parse_ai_output(raw: dict) -> dict:
    """Validate and normalise AI JSON output. Raises ValueError on bad output."""
    missing = _REQUIRED_AI_FIELDS - raw.keys()
    if missing:
        raise ValueError(f"AI output missing fields: {missing}")
    cat = raw.get("root_cause_category")
    if cat not in _VALID_CATEGORIES:
        raise ValueError(f"Invalid root_cause_category: {cat!r}")
    conf = raw.get("confidence")
    if conf not in _VALID_CONFIDENCE:
        raise ValueError(f"Invalid confidence: {conf!r}")

    signals = raw.get("filter_signals") or []
    return {
        "root_cause_category":  cat,
        "root_cause_detail":    str(raw.get("root_cause_detail") or ""),
        "is_prompt_optimizable": 1 if raw.get("is_prompt_optimizable") else 0,
        "prompt_issue":         raw.get("prompt_issue") or None,
        "filter_signals":       json.dumps(signals) if isinstance(signals, list) else str(signals),
        "analysis_confidence":  conf,
    }


def _run_phase2(llm, case: dict, tag_updates: dict, model: str) -> dict:
    """Call failure_case_analysis and return validated AI update fields."""
    variables = _build_ai_variables(case, tag_updates)
    raw = llm.call_json(
        "failure_case_analysis",
        variables,
        model,
        trace_id=case["push_record_id"],
    )
    return _parse_ai_output(raw)


def run_once(settings, evo_db: EvolutionDB) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    due = evo_db.pending_due(now_iso)
    if not due:
        return

    print(f"[scheduler] {len(due)} case(s) due for T+24h tagging", flush=True)

    # Phase 2: only build LLM client when configured
    llm = None
    if settings.langfuse_public_key and settings.llm_api_key:
        from evolution.llm import LLMClient
        llm = LLMClient.from_settings(settings)

    client = RadarClient(
        settings.radar_base_url,
        settings.radar_username,
        settings.radar_password,
    )
    radar_ok = False
    try:
        client.login()
        radar_ok = True
    except Exception as e:
        print(f"[scheduler] radar login failed (will skip narrative/gain fetch): {e}", flush=True)

    for case in due:
        pid = case["push_record_id"]
        try:
            if not evo_db.is_trusted_signal(pid):
                evo_db.mark_untrusted_skipped(pid)
                print(f"[scheduler] skipped untrusted signal {case.get('symbol')} ({pid[:8]})", flush=True)
                continue

            narrative_hit, gain_24h_pct = None, None
            if radar_ok:
                narrative_hit, gain_24h_pct = _fetch_t24h(client, case)
            updates = run_tag(
                case,
                cli=settings.gmgn_cli,
                narrative_hit=narrative_hit,
                gain_24h_pct=gain_24h_pct,
            )

            # Phase 2: AI analysis for failure cases
            if llm is not None and updates.get("is_failure_case") == 1:
                try:
                    ai_fields = _run_phase2(llm, case, updates, settings.llm_model_fast)
                    updates.update(ai_fields)
                except Exception as e:
                    print(f"[scheduler] AI failed {pid[:8]}: {e}", flush=True)
                    updates["analysis_status"] = "failed"
                    updates["last_error"] = f"AI: {str(e)[:400]}"
                    updates["retry_count"] = (case.get("retry_count") or 0) + 1
                    evo_db.update_tagging(pid, updates)
                    continue

            evo_db.update_tagging(pid, updates)
            print(
                f"[scheduler] tagged {case.get('symbol')} ({pid[:8]}): "
                f"status={updates.get('analysis_status')} tags={updates.get('tags')}",
                flush=True,
            )
        except Exception as e:
            evo_db.mark_failed(pid, str(e))
            print(f"[scheduler] failed {pid}: {e}", flush=True)

    client.close()
    if llm:
        llm.flush()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _load_env()
    settings = load_settings()
    evo_db = EvolutionDB(settings.db_path)
    evo_db.init_schema()
    run_once(settings, evo_db)
    evo_db.close()


if __name__ == "__main__":
    main()
