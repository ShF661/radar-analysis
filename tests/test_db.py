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
