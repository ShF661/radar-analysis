"""Integration tests for DB filter methods, collector filter path, and signal-filter API endpoints."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.collector import process_new_task
from app.db import Database

FX = Path(__file__).parent / "fixtures"


# ─────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────

def _task():
    return json.loads((FX / "task.json").read_text(encoding="utf-8"))


def _clean_snap():
    return {
        "gmgn_ok": True,
        "renounced_mint": "yes",
        "renounced_freeze": "yes",
        "can_not_sell": 0,
        "rug_ratio": 0.1,
        "is_honeypot": "no",
        "is_blacklist": "no",
        "buy_tax": 0.02,
        "sell_tax": 0.02,
        "market_cap": 500_000,
        "liquidity": 30_000,
        "volume_24h": 100_000,
        "holder_count": 400,
        "top10_rate": 0.25,
        "dev_hold_rate": 0.04,
        "bundler_rate": 0.20,
        "bot_degen_rate": 0.15,
        "entrapment_rate": 0.05,
        "rat_rate": 0.05,
        "fresh_wallet_rate": 0.30,
        "smart_wallets": 3,
        "kol_wallets": 1,
        "creation_timestamp": 1_718_500_000,
    }


def _db(tmp_path) -> Database:
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    return db


def _client(tmp_path) -> TestClient:
    db = _db(tmp_path)
    return TestClient(create_app(db, db_path=str(tmp_path / "t.db")))


# ─────────────────────────────────────────────
# DB: mark_filtered / get_filtered / clear_filter
# ─────────────────────────────────────────────

def test_db_mark_filtered_writes_fields(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({"task_id": "t1", "chain": "sol", "track_status": "tracking",
                     "base_market_cap": 500_000})
    db.mark_filtered("t1", "safety", ["蜜罐合约", "rug风险=35%"], {"gmgn_ok": True})
    row = db.get("t1")
    assert row["filter_type"] == "safety"
    assert row["track_status"] == "done"
    assert row["gmgn_ok"] == 1
    matched = json.loads(row["matched_rules"])
    assert matched == ["蜜罐合约", "rug风险=35%"]


def test_db_get_filtered_returns_only_filtered(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({"task_id": "clean", "chain": "sol", "track_status": "tracking"})
    db.insert_entry({"task_id": "bad",   "chain": "sol", "track_status": "tracking"})
    db.mark_filtered("bad", "metric", ["集群机器人盘"], {"gmgn_ok": True})

    rows = db.get_filtered()
    ids = {r["task_id"] for r in rows}
    assert "bad" in ids
    assert "clean" not in ids


def test_db_get_filtered_chain_filter(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({"task_id": "sol_bad", "chain": "sol", "track_status": "tracking"})
    db.insert_entry({"task_id": "eth_bad", "chain": "eth", "track_status": "tracking"})
    db.mark_filtered("sol_bad", "safety", ["r"], {"gmgn_ok": True})
    db.mark_filtered("eth_bad", "safety", ["r"], {"gmgn_ok": True})

    sol_rows = db.get_filtered(chain="sol")
    assert all(r["chain"] == "sol" for r in sol_rows)
    assert len(sol_rows) == 1


def test_db_clear_filter_resets_fields(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({"task_id": "t1", "chain": "sol", "track_status": "tracking"})
    db.mark_filtered("t1", "metric", ["r"], {"gmgn_ok": True})
    db.clear_filter("t1")
    row = db.get("t1")
    assert row["filter_type"] is None
    assert row["matched_rules"] is None
    assert row["track_status"] == "tracking"


# ─────────────────────────────────────────────
# Collector: process_new_task with filter_config
# ─────────────────────────────────────────────

def test_collector_filter_blocks_safety(tmp_path):
    db = _db(tmp_path)
    bad_snap = {**_clean_snap(), "renounced_mint": "no"}  # SOL safety fail
    filter_cfg = {"metric_filter_enabled": False, "metric_rules": [], "high_tax_threshold": 0.10}

    process_new_task(db, _task(), lambda c, a: bad_snap, filter_config=filter_cfg)

    row = db.get("task-123")
    assert row is not None
    assert row["filter_type"] == "safety"
    assert row["track_status"] == "done"
    matched = json.loads(row["matched_rules"])
    assert len(matched) > 0


def test_collector_filter_blocks_metric(tmp_path):
    db = _db(tmp_path)
    # bundler_rate=0.70 → 70% → hits rule ≥60
    bad_snap = {**_clean_snap(), "bundler_rate": 0.70, "bot_degen_rate": 0.65}
    filter_cfg = {
        "metric_filter_enabled": True,
        "metric_rules": [{
            "id": "r1", "name": "集群机器人盘", "enabled": True,
            "conditions": [
                {"field": "bundler_rate",   "op": ">=", "value": 60},
                {"field": "bot_degen_rate", "op": ">=", "value": 60},
            ],
        }],
        "high_tax_threshold": 0.10,
    }

    process_new_task(db, _task(), lambda c, a: bad_snap, filter_config=filter_cfg)

    row = db.get("task-123")
    assert row["filter_type"] == "metric"
    matched = json.loads(row["matched_rules"])
    assert "集群机器人盘" in matched


def test_collector_filter_pass_through_when_none(tmp_path):
    db = _db(tmp_path)
    # filter_config=None → no filtering at all
    process_new_task(db, _task(), lambda c, a: _clean_snap(), filter_config=None)
    row = db.get("task-123")
    assert row is not None
    assert row["filter_type"] is None


def test_collector_filter_gmgn_fail_passes_through(tmp_path):
    db = _db(tmp_path)
    fail_snap = {**_clean_snap(), "gmgn_ok": False, "renounced_mint": "no"}
    filter_cfg = {"metric_filter_enabled": False, "metric_rules": [], "high_tax_threshold": 0.10}
    process_new_task(db, _task(), lambda c, a: fail_snap, filter_config=filter_cfg)
    row = db.get("task-123")
    assert row["filter_type"] is None  # gmgn_ok=False → pass-through


def test_collector_filter_clean_token_not_filtered(tmp_path):
    db = _db(tmp_path)
    filter_cfg = {
        "metric_filter_enabled": True,
        "metric_rules": [{
            "id": "r1", "name": "高集群", "enabled": True,
            "conditions": [{"field": "bundler_rate", "op": ">=", "value": 90}],
        }],
        "high_tax_threshold": 0.10,
    }
    process_new_task(db, _task(), lambda c, a: _clean_snap(), filter_config=filter_cfg)
    row = db.get("task-123")
    assert row["filter_type"] is None
    assert row["track_status"] == "tracking"


# ─────────────────────────────────────────────
# API: GET/PUT /api/v1/signal-filter/config
# ─────────────────────────────────────────────

def test_api_get_config_returns_defaults(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/v1/signal-filter/config")
    assert r.status_code == 200
    body = r.json()
    assert body["metric_filter_enabled"] is False
    assert body["metric_rules"] == []
    assert body["high_tax_threshold"] == pytest.approx(0.10)


def test_api_put_config_persists(tmp_path):
    c = _client(tmp_path)
    payload = {
        "metric_filter_enabled": True,
        "metric_rules": [{
            "id": "r1", "name": "test", "enabled": True,
            "conditions": [{"field": "bundler_rate", "op": ">=", "value": 60}],
        }],
        "high_tax_threshold": 0.08,
    }
    r = c.put("/api/v1/signal-filter/config", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["metric_filter_enabled"] is True
    assert len(body["metric_rules"]) == 1

    # Second GET returns saved config
    r2 = c.get("/api/v1/signal-filter/config")
    assert r2.json()["metric_filter_enabled"] is True
    assert r2.json()["high_tax_threshold"] == pytest.approx(0.08)


def test_api_put_config_invalid_missing_field(tmp_path):
    c = _client(tmp_path)
    # metric_rules must be a list, not a string
    r = c.put("/api/v1/signal-filter/config", json={"metric_rules": "bad"})
    assert r.status_code == 422


# ─────────────────────────────────────────────
# API: GET /api/v1/filtered-tokens
# ─────────────────────────────────────────────

def test_api_filtered_tokens_empty(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/v1/filtered-tokens")
    assert r.status_code == 200
    assert r.json()["data"] == []


def test_api_filtered_tokens_returns_filtered(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({"task_id": "f1", "chain": "sol", "symbol": "BAD",
                     "track_status": "tracking"})
    db.mark_filtered("f1", "safety", ["蜜罐合约"], {"gmgn_ok": True})
    c = TestClient(create_app(db, db_path=str(tmp_path / "t.db")))
    r = c.get("/api/v1/filtered-tokens")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["task_id"] == "f1"
    # matched_rules should be deserialized to a list
    assert data[0]["matched_rules"] == ["蜜罐合约"]


def test_api_filtered_tokens_chain_filter(tmp_path):
    db = _db(tmp_path)
    for tid, chain in [("a", "sol"), ("b", "eth")]:
        db.insert_entry({"task_id": tid, "chain": chain, "track_status": "tracking"})
        db.mark_filtered(tid, "metric", ["r"], {"gmgn_ok": True})
    c = TestClient(create_app(db, db_path=str(tmp_path / "t.db")))
    r = c.get("/api/v1/filtered-tokens?chain=sol")
    data = r.json()["data"]
    assert all(d["chain"] == "sol" for d in data)


# ─────────────────────────────────────────────
# API: POST /api/v1/tasks/{id}/rescue
# ─────────────────────────────────────────────

def test_api_rescue_clears_filter(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({"task_id": "t1", "chain": "sol", "track_status": "tracking"})
    db.mark_filtered("t1", "safety", ["rug"], {"gmgn_ok": True})
    c = TestClient(create_app(db, db_path=str(tmp_path / "t.db")))
    r = c.post("/api/v1/tasks/t1/rescue")
    assert r.status_code == 200
    assert r.json()["task_id"] == "t1"
    row = db.get("t1")
    assert row["filter_type"] is None
    assert row["track_status"] == "tracking"


def test_api_rescue_404_on_missing(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/v1/tasks/nonexistent/rescue")
    assert r.status_code == 404


def test_api_rescue_400_when_not_filtered(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({"task_id": "t1", "chain": "sol", "track_status": "tracking"})
    c = TestClient(create_app(db, db_path=str(tmp_path / "t.db")))
    r = c.post("/api/v1/tasks/t1/rescue")
    assert r.status_code == 400
