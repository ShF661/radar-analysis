from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.chip_risk import chip_risk_summary, compute_chip_risk
from app.db import Database
from app.features import DEFAULT_THRESHOLDS, FEATURE_LABELS
from app.gmgn import fetch_snapshot, normalize_chain
from app.signal_filter_store import load_config, save_config

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ─────────────────────────────────────────────
# Pydantic schemas for signal-filter endpoints
# ─────────────────────────────────────────────

class FilterCondition(BaseModel):
    field: str
    op: str
    value: float
    value2: float | None = None


class MetricRule(BaseModel):
    id: str
    name: str
    enabled: bool = True
    conditions: list[FilterCondition] = []


class SignalFilterConfig(BaseModel):
    metric_filter_enabled: bool = False
    metric_rules: list[MetricRule] = []
    high_tax_threshold: float = 0.10


# ─────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────

def create_app(db: Database, db_path: str = "./radar.db", gmgn_cli: str = "gmgn-cli") -> FastAPI:
    app = FastAPI(title="金狗雷达 GMGN 特征分析")

    @app.get("/api/tokens")
    def list_tokens():
        return db.all_backtested()

    @app.get("/api/tokens/{task_id}")
    def token_detail(task_id: str):
        row = db.get(task_id)
        if not row or not row.get("backtest_id"):
            raise HTTPException(status_code=404, detail="not found")
        return row

    @app.get("/api/defaults")
    def defaults():
        # 仅提供阈值与特征中文名；分桶/特征/统计逻辑全部在前端（唯一权威）。
        return {"thresholds": DEFAULT_THRESHOLDS, "feature_labels": FEATURE_LABELS}

    # ── Signal filter config ──────────────────

    @app.get("/api/v1/signal-filter/config")
    def get_signal_filter_config() -> dict[str, Any]:
        return load_config(db_path)

    @app.put("/api/v1/signal-filter/config")
    def update_signal_filter_config(body: SignalFilterConfig) -> dict[str, Any]:
        data = body.model_dump()
        return save_config(db_path, data)

    # ── Filtered tokens ───────────────────────

    @app.get("/api/v1/filtered-tokens")
    def list_filtered_tokens(chain: str | None = None, limit: int = 50):
        rows = db.get_filtered(limit=limit, chain=chain)
        for r in rows:
            # matched_rules is stored as JSON string; deserialize for the client
            if isinstance(r.get("matched_rules"), str):
                try:
                    r["matched_rules"] = json.loads(r["matched_rules"])
                except (json.JSONDecodeError, TypeError):
                    r["matched_rules"] = []
        return {"data": rows, "total": len(rows)}

    # ── Chip risk (by task_id, from DB) ──────────
    @app.get("/api/v1/tokens/{task_id}/chip-risk")
    def get_chip_risk(task_id: str):
        row = db.get(task_id)
        if not row:
            raise HTTPException(status_code=404, detail="task not found")
        result = chip_risk_summary(row)
        result["task_id"] = task_id
        return result

    # ── Chip risk (real-time, by chain+address) ──
    @app.get("/api/v1/chip-risk")
    def get_chip_risk_live(chain: str, address: str):
        chain = normalize_chain(chain)
        if not chain or not address:
            raise HTTPException(status_code=400, detail="chain and address are required")
        snap = fetch_snapshot(gmgn_cli, chain, address)
        if not snap.get("gmgn_ok"):
            return {
                "chain": chain,
                "address": address,
                "gmgn_ok": False,
                "warnings": [],
                "triggered_count": 0,
                "raw": {f: None for f in ("entrapment_rate", "bundler_rate", "dev_hold_rate", "fresh_wallet_rate", "top10_rate")},
            }
        result = chip_risk_summary(snap)
        result["chain"] = chain
        result["address"] = address
        result["gmgn_ok"] = True
        return result

    # ── Rescue ───────────────────────────────

    @app.post("/api/v1/tasks/{task_id}/rescue")
    def rescue_task(task_id: str):
        row = db.get(task_id)
        if not row:
            raise HTTPException(status_code=404, detail="task not found")
        if not row.get("filter_type"):
            raise HTTPException(status_code=400, detail="task is not filtered")
        db.clear_filter(task_id)
        return {"task_id": task_id, "status": "rescued"}

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app
