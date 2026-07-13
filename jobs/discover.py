"""One-shot discover: fetch radar tasks and save new ones to Neon PostgreSQL."""
from __future__ import annotations
import sys
import os


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
    from app.collector import Collector, process_new_task, process_prefiltered_task
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

    try:
        for task in c._client.fetch_completed_tasks():
            base = parse_task(task)
            if not base or base["chain"] not in settings.chains:
                continue
            if db.exists(base["task_id"]):
                if base.get("grade"):
                    cur = db.get(base["task_id"])
                    if cur and not cur.get("grade"):
                        db.update_grade(base["task_id"], base["grade"])
                continue
            process_new_task(db, task, c._snapshot_fn, c._backtest_fn, evo_db, filter_config=filter_config)
            count += 1

        for task in c._client.fetch_filtered_tasks():
            base = parse_task(task)
            if not base or base["chain"] not in settings.chains:
                continue
            if db.exists(base["task_id"]):
                continue
            process_prefiltered_task(db, task)
            count += 1
    finally:
        c._client.close()
        db.close()
        evo_db.close()

    print(f"[discover] done, {count} new tasks saved", flush=True)


if __name__ == "__main__":
    main()
