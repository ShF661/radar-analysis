from __future__ import annotations

import argparse

import uvicorn

from app.api import create_app
from app.collector import Collector
from app.config import load_settings
from app.db import Database


def main() -> None:
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
