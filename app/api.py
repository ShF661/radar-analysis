from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.analysis import (DEFAULT_DROP_BUCKETS, DEFAULT_GAIN_BUCKETS, cohort_analysis)
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
        return {
            "gain_buckets": DEFAULT_GAIN_BUCKETS,
            "drop_buckets": DEFAULT_DROP_BUCKETS,
            "thresholds": DEFAULT_THRESHOLDS,
            "feature_labels": FEATURE_LABELS,
        }

    @app.post("/api/analysis")
    def analysis(payload: dict):
        dimension = payload.get("dimension", "peak_gain_pct")
        default_buckets = DEFAULT_DROP_BUCKETS if dimension == "max_drop_pct" else DEFAULT_GAIN_BUCKETS
        buckets = payload.get("buckets") or default_buckets
        thresholds = {**DEFAULT_THRESHOLDS, **(payload.get("thresholds") or {})}
        return cohort_analysis(db.all(), dimension, buckets, thresholds)

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app
