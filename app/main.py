from __future__ import annotations

import argparse
import sys
import os

import uvicorn

from app.api import create_app
from app.collector import Collector
from app.config import load_settings
from app.db import Database


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
    db = Database(settings.db_path)
    db.init_schema()

    if args.mode in ("collector", "all"):
        Collector(settings, db).run()

    if args.mode in ("api", "all"):
        uvicorn.run(create_app(db), host="127.0.0.1", port=settings.api_port)
    elif args.mode == "collector":
        import time
        print("[collector] running; Ctrl+C to stop")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
