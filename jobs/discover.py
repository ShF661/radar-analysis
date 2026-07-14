"""One-shot discover: fetch radar tasks and save new ones to Neon PostgreSQL."""
from __future__ import annotations
import sys
import os
import time


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
    _load_env()
    from app.config import load_settings
    from app.db_pg import Database
    from evolution.db_pg import EvolutionDB
    from app.collector import (
        Collector,
        process_new_task,
        process_prefiltered_task,
        snapshot_from_preanalysis,
    )
    from app.radar import parse_task
    from app.signal_filter_store import load_config

    settings = load_settings()
    if not settings.database_url:
        print("[discover] DATABASE_URL not set", flush=True)
        sys.exit(1)

    db = Database(settings.database_url)
    db.init_schema()
    evo_db = EvolutionDB(settings.database_url)
    evo_db.init_schema()

    c = Collector(settings, db, evo_db)
    try:
        c._client.login()
    except Exception as e:
        print(f"[discover] login failed: {e}", flush=True)
        sys.exit(1)

    filter_config = load_config(settings.db_path)
    count = 0
    gmgn_attempted = 0
    gmgn_succeeded = 0
    pass_count = 0
    run_seconds = max(0, int(os.getenv("DISCOVER_RUN_SECONDS", "0")))
    interval = max(5, int(os.getenv("DISCOVER_INTERVAL", "30")))
    catchup_pages = max(1, int(os.getenv("DISCOVER_CATCHUP_PAGES", "10")))
    deadline = time.monotonic() + run_seconds if run_seconds else None

    try:
        while True:
            try:
                max_pages = catchup_pages if pass_count == 0 else 1
                for task in c._client.fetch_completed_tasks(max_pages=max_pages):
                    base = parse_task(task)
                    if not base or base["chain"] not in settings.chains:
                        continue
                    if db.exists(base["task_id"]):
                        cur = db.get(base["task_id"])
                        fallback = snapshot_from_preanalysis(task)
                        if cur and not cur.get("gmgn_ok") and fallback.get("gmgn_ok"):
                            db.update_snapshot(base["task_id"], fallback)
                        if base.get("grade"):
                            if cur and not cur.get("grade"):
                                db.update_grade(base["task_id"], base["grade"])
                        continue
                    process_new_task(db, task, c._snapshot_fn, c._backtest_fn, evo_db, filter_config=filter_config)
                    count += 1
                    gmgn_attempted += 1
                    saved = db.get(base["task_id"])
                    if saved and saved.get("gmgn_ok"):
                        gmgn_succeeded += 1

                for task in c._client.fetch_filtered_tasks(max_pages=max_pages):
                    base = parse_task(task)
                    if not base or base["chain"] not in settings.chains:
                        continue
                    if db.exists(base["task_id"]):
                        continue
                    process_prefiltered_task(db, task)
                    count += 1
                pass_count += 1
            except Exception as exc:
                print(f"[discover] pass failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                if deadline is None:
                    raise
                try:
                    c._client.login()
                except Exception as login_exc:
                    print(f"[discover] re-login failed: {login_exc}", file=sys.stderr, flush=True)

            if deadline is None or time.monotonic() >= deadline:
                break
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
    finally:
        c._client.close()
        db.close()
        evo_db.close()

    print(
        f"[discover] done, passes={pass_count} saved={count} gmgn_attempted={gmgn_attempted} "
        f"gmgn_succeeded={gmgn_succeeded} gmgn_failed={gmgn_attempted - gmgn_succeeded}",
        flush=True,
    )
    if gmgn_attempted and gmgn_succeeded == 0:
        print("[discover] all GMGN snapshot attempts failed", file=sys.stderr, flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
