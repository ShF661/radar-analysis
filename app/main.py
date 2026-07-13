from __future__ import annotations

import argparse
import sys
import os

import uvicorn

from app.api import create_app
from app.collector import Collector
from app.config import load_settings
from app.db import Database
from evolution.db import EvolutionDB
from evolution.scheduler import run_once as scheduler_run_once


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
    parser = argparse.ArgumentParser(description="金狗雷达 GMGN 特征分析")
    parser.add_argument("mode", choices=["collector", "api", "all"], help="运行模式")
    args = parser.parse_args()

    settings = load_settings()
    if settings.database_url:
        from app.db_pg import Database as DbCls
        from evolution.db_pg import EvolutionDB as EvoDbCls
        db_arg = settings.database_url
    else:
        DbCls = Database  # type: ignore[assignment]
        EvoDbCls = EvolutionDB  # type: ignore[assignment]
        db_arg = settings.db_path
    db = DbCls(db_arg)
    db.init_schema()
    evo_db = EvoDbCls(db_arg)
    evo_db.init_schema()

    if args.mode in ("collector", "all"):
        Collector(settings, db, evo_db).run()

    if args.mode == "all":
        import threading
        def _scheduler_loop():
            import time
            while True:
                try:
                    scheduler_run_once(settings, evo_db)
                except Exception as e:
                    print(f"[scheduler-loop] error: {e}", flush=True)
                time.sleep(300)  # every 5 minutes

        def _daily_report_loop():
            import time
            from evolution.report import build_daily_report, build_local_summary, build_no_data_notice
            from evolution.feishu import push
            from datetime import datetime, timedelta, timezone
            cn_tz = timezone(timedelta(hours=8))
            last_date = None
            while True:
                now = datetime.now(timezone.utc)
                # 20:30 Beijing time = 12:30 UTC
                if now.hour == 12 and now.minute == 30:
                    today = now.astimezone(cn_tz).strftime("%Y-%m-%d")
                    if last_date != today and settings.feishu_webhook:
                        try:
                            from evolution.db_pg import EvolutionDB as _EvoDb  # noqa
                            _EvoDbCls = _EvoDb if settings.database_url else EvolutionDB
                            _db_arg = settings.database_url or settings.db_path
                            _db = _EvoDbCls(_db_arg)
                            try:
                                stats = _db.daily_stats(today)
                                if not stats.get("total"):
                                    text = build_no_data_notice(today)
                                else:
                                    from evolution.llm import LLMClient
                                    from evolution.report import build_ai_summary_vars
                                    ai_summary = None
                                    failure_cases = _db.failure_cases_today(today)
                                    security_cases = _db.security_risk_cases_today(today)
                                    if settings.langfuse_public_key and settings.llm_api_key:
                                        try:
                                            llm = LLMClient.from_settings(settings)
                                            if failure_cases or security_cases:
                                                variables = build_ai_summary_vars(today, stats, failure_cases, security_cases)
                                                ai_summary = llm.call_text("daily_improvement_report", variables, settings.llm_model_pro)
                                                llm.flush()
                                        except Exception as e:
                                            print(f"[daily-report] AI summary failed: {e}", flush=True)
                                    if ai_summary is None and (failure_cases or security_cases):
                                        ai_summary = build_local_summary(stats, failure_cases, security_cases)
                                    text = build_daily_report(today, stats, ai_summary)
                            finally:
                                _db.close()
                            push(settings.feishu_webhook, text)
                            last_date = today
                            print(f"[daily-report] pushed for {today}", flush=True)
                        except Exception as e:
                            print(f"[daily-report] error: {e}", flush=True)
                time.sleep(60)  # check every minute

        t1 = threading.Thread(target=_scheduler_loop, daemon=True)
        t2 = threading.Thread(target=_daily_report_loop, daemon=True)
        t1.start()
        t2.start()
        print("[scheduler-loop] started (every 5 min)", flush=True)
        print("[daily-report-loop] started (fires at 20:30 Beijing time)", flush=True)

    if args.mode in ("api", "all"):
        uvicorn.run(create_app(db, db_path=settings.db_path, gmgn_cli=settings.gmgn_cli), host="127.0.0.1", port=settings.api_port)
    elif args.mode == "collector":
        import time
        print("[collector] running; Ctrl+C to stop")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
