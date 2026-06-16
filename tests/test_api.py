from fastapi.testclient import TestClient

from app.api import create_app
from app.db import Database


def _seed(db):
    db.insert_entry({"task_id": "low", "symbol": "L", "address": "a", "chain": "sol",
                     "peak_gain_pct": 10, "max_drop_pct": 70, "smart_wallets": 0,
                     "base_market_cap": 100, "track_status": "done"})
    db.insert_entry({"task_id": "hi", "symbol": "H", "address": "b", "chain": "sol",
                     "peak_gain_pct": 200, "max_drop_pct": 10, "smart_wallets": 3,
                     "base_market_cap": 100, "track_status": "done"})


def _client(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    _seed(db)
    return TestClient(create_app(db))


def test_tokens_endpoint_lists_all(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/tokens")
    assert r.status_code == 200
    assert {t["task_id"] for t in r.json()} == {"low", "hi"}


def test_token_detail(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/tokens/low")
    assert r.status_code == 200
    assert r.json()["symbol"] == "L"
    assert c.get("/api/tokens/missing").status_code == 404


def test_defaults_endpoint(tmp_path):
    c = _client(tmp_path)
    d = c.get("/api/defaults").json()
    assert "gain_buckets" in d and "drop_buckets" in d and "thresholds" in d


def test_analysis_endpoint(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/analysis", json={"dimension": "peak_gain_pct"})
    assert r.status_code == 200
    body = r.json()
    low = next(b for b in body["buckets"] if b["label"] == "<50%")
    smz = next(f for f in low["features"] if f["feature"] == "smart_money_zero")
    assert smz["bucket_rate"] == 1.0
