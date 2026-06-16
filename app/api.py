from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.db import Database
from app.features import DEFAULT_THRESHOLDS, FEATURE_LABELS

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(db: Database) -> FastAPI:
    app = FastAPI(title="金狗雷达 GMGN 特征分析")

    @app.get("/api/tokens")
    def list_tokens():
        return db.all()

    @app.get("/api/tokens/{task_id}")
    def token_detail(task_id: str):
        row = db.get(task_id)
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return row

    @app.get("/api/defaults")
    def defaults():
        # 仅提供阈值与特征中文名；分桶/特征/统计逻辑全部在前端（唯一权威）。
        return {"thresholds": DEFAULT_THRESHOLDS, "feature_labels": FEATURE_LABELS}

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app
