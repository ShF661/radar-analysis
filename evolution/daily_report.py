"""
Daily report script — run at 20:30 via Windows Task Scheduler.

  python -m evolution.daily_report
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from app.config import load_settings
from evolution.db import EvolutionDB
from evolution.feishu import push
from evolution.report import (
    build_ai_summary_vars,
    build_daily_report,
    build_filtered_section,
    build_local_summary,
    build_no_data_notice,
)

CN_TZ = timezone(timedelta(hours=8))


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


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    _load_env()
    settings = load_settings()

    if not settings.feishu_webhook:
        print("[daily_report] FEISHU_WEBHOOK not set, aborting", flush=True)
        sys.exit(1)

    evo_db = EvolutionDB(settings.db_path)
    try:
        evo_db.init_schema()

        today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
        stats = evo_db.daily_stats(today)
        filtered_cases = evo_db.filtered_cases_today(today)

        if not stats.get("total"):
            text = build_no_data_notice(today)
            if filtered_cases:
                text += "\n\n" + build_filtered_section(filtered_cases)
            push(settings.feishu_webhook, text)
            print("[daily_report] no data, pushed notice", flush=True)
            return

        failure_cases = evo_db.failure_cases_today(today)
        security_cases = evo_db.security_risk_cases_today(today)

        # Phase 2: AI summary if LLM is configured. Fall back to deterministic
        # local aggregation so the 20:30 report still contains Track A/B.
        ai_summary = None
        if settings.langfuse_public_key and settings.llm_api_key:
            try:
                from evolution.llm import LLMClient
                llm = LLMClient.from_settings(settings)
                if failure_cases or security_cases:
                    variables = build_ai_summary_vars(today, stats, failure_cases, security_cases)
                    ai_summary = llm.call_text(
                        "daily_improvement_report",
                        variables,
                        settings.llm_model_pro,
                    )
                    llm.flush()
            except Exception as e:
                print(f"[daily_report] AI summary failed: {e}", flush=True)

        if ai_summary is None and (failure_cases or security_cases):
            ai_summary = build_local_summary(stats, failure_cases, security_cases)
    finally:
        evo_db.close()

    text = build_daily_report(today, stats, ai_summary, filtered_cases)
    print(text, flush=True)
    push(settings.feishu_webhook, text)
    print("[daily_report] pushed to Feishu", flush=True)


if __name__ == "__main__":
    main()
