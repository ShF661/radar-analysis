from app.db import Database


def test_insert_and_exists(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    assert db.exists("task-1") is False
    db.insert_entry({"task_id": "task-1", "symbol": "TKN", "address": "a",
                     "chain": "sol", "market_cap": 500000, "base_market_cap": 500000,
                     "track_status": "tracking"})
    assert db.exists("task-1") is True


def test_update_price_sets_gain_and_drop(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "t", "base_market_cap": 100.0, "track_status": "tracking"})
    db.update_price("t", current_market_cap=150.0)   # +50%
    db.update_price("t", current_market_cap=40.0)    # -60%
    row = db.get("t")
    assert row["current_gain_pct"] == -60.0
    assert row["peak_gain_pct"] == 50.0
    assert row["max_drop_pct"] == 60.0


def test_update_price_skips_backtest_controlled_rows(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "t", "base_market_cap": 100.0, "track_status": "tracking",
                     "backtest_id": "bt-1", "peak_market_cap": 180.0,
                     "peak_gain_pct": 80.0, "max_drop_pct": 20.0})
    db.update_price("t", current_market_cap=250.0)
    row = db.get("t")
    assert row["peak_market_cap"] == 180.0
    assert row["peak_gain_pct"] == 80.0
    assert row["max_drop_pct"] == 20.0


def test_apply_backtest_metrics_updates_performance_only(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "t", "base_market_cap": 100.0, "track_status": "tracking",
                     "smart_wallets": 3, "kol_wallets": 1})
    db.apply_backtest_metrics("t", {
        "backtest_id": "bt-1",
        "base_market_cap": 120.0,
        "peak_market_cap": 240.0,
        "peak_gain_pct": 100.0,
        "max_drop_pct": 30.0,
        "settlement_market_cap": 60.0,
        "settlement_gain_pct": -50.0,
        "status": "settled",
    })
    row = db.get("t")
    assert row["backtest_id"] == "bt-1"
    assert row["base_market_cap"] == 120.0
    assert row["peak_market_cap"] == 240.0
    assert row["peak_gain_pct"] == 100.0
    assert row["max_drop_pct"] == 30.0
    assert row["settlement_market_cap"] == 60.0
    assert row["final_gain_pct"] == -50.0
    assert row["track_status"] == "done"
    assert row["smart_wallets"] == 3
    assert row["kol_wallets"] == 1


def test_finalize_marks_done(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "t", "base_market_cap": 100.0, "track_status": "tracking"})
    db.update_price("t", current_market_cap=120.0)
    db.finalize("t")
    row = db.get("t")
    assert row["track_status"] == "done"
    assert row["final_gain_pct"] == 20.0


def test_tracking_ids_filters_done(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "a", "track_status": "tracking", "base_market_cap": 1.0})
    db.insert_entry({"task_id": "b", "track_status": "done", "base_market_cap": 1.0})
    assert db.tracking_ids() == ["a"]


def test_enrichment_ids_include_done_rows_and_respect_attempt_limit(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "done-missing", "address": "a", "chain": "sol",
                     "track_status": "done", "gmgn_ok": 0, "enrich_attempts": 0})
    db.insert_entry({"task_id": "ok", "address": "b", "chain": "sol",
                     "track_status": "done", "gmgn_ok": 1, "renounced_mint": "yes"})
    db.insert_entry({"task_id": "exhausted", "address": "c", "chain": "sol",
                     "track_status": "done", "gmgn_ok": 0, "enrich_attempts": 5})

    assert db.enrichment_ids() == ["done-missing"]
