"""One-shot evolution scheduler: tag T+24h cases and run AI analysis."""
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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _load_env()
    from app.config import load_settings
    from evolution.db_pg import EvolutionDB
    from evolution.scheduler import run_once

    settings = load_settings()
    if not settings.database_url:
        print("[evolution] DATABASE_URL not set", flush=True)
        sys.exit(1)

    evo_db = EvolutionDB(settings.database_url)
    evo_db.init_schema()
    try:
        run_once(settings, evo_db)
    finally:
        evo_db.close()


if __name__ == "__main__":
    main()
