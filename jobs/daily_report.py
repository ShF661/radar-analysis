"""One-shot daily report: build stats and push to Feishu."""
from __future__ import annotations
import sys
import os
from datetime import datetime, timedelta, timezone


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
        os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _load_env()
    from app.config import load_settings
    from evolution.db_pg import EvolutionDB
    from evolution.report import build_daily_report, build_local_summary, build_no_data_notice
    from evolution.feishu import push

    settings = load_settings()
    if not settings.database_url:
        print("[daily-report] DATABASE_URL not set", flush=True)
        sys.exit(1)

    cn_tz = timezone(timedelta(hours=8))
    today = datetime.now(timezone.utc).astimezone(cn_tz).strftime("%Y-%m-%d")
    print(f"[daily-report] generating report for {today}", flush=True)

    db = EvolutionDB(settings.database_url)
    db.init_schema()
    try:
        stats = db.daily_stats(today)
        if not stats.get("total"):
            text = build_no_data_notice(today)
        else:
            ai_summary = None
            failure_cases = db.failure_cases_today(today)
            security_cases = db.security_risk_cases_today(today)
            if settings.langfuse_public_key and settings.llm_api_key and (failure_cases or security_cases):
                try:
                    from evolution.llm import LLMClient
                    from evolution.report import build_ai_summary_vars
                    llm = LLMClient.from_settings(settings)
                    variables = build_ai_summary_vars(today, stats, failure_cases, security_cases)
                    ai_summary = llm.call_text("daily_improvement_report", variables, settings.llm_model_pro)
                    llm.flush()
                except Exception as e:
                    print(f"[daily-report] AI failed: {e}", flush=True)
            if ai_summary is None and (failure_cases or security_cases):
                ai_summary = build_local_summary(stats, failure_cases, security_cases)
            filtered_cases = db.filtered_cases_today(today)
            text = build_daily_report(today, stats, ai_summary, filtered_cases)
    finally:
        db.close()

    if settings.feishu_webhook:
        push(settings.feishu_webhook, text)
        print(f"[daily-report] pushed for {today}", flush=True)
    else:
        print("[daily-report] no FEISHU_WEBHOOK set, skipping push", flush=True)


if __name__ == "__main__":
    main()
