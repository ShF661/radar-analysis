import json
from pathlib import Path

from app.collector import build_entry_row, process_new_task, refresh_one
from app.db import Database

FX = Path(__file__).parent / "fixtures"


def _task():
    return json.loads((FX / "task.json").read_text(encoding="utf-8"))


def _snapshot():
    return {
        "gmgn_ok": True, "price": 0.0005, "liquidity": 25000, "market_cap": 500000,
        "volume_24h": 120000, "holder_count": 320, "top10_rate": 0.42,
        "dev_hold_rate": 0.06, "rat_rate": 0.12, "entrapment_rate": 0.08,
        "bundler_rate": 0.35, "fresh_wallet_rate": 0.55, "bot_degen_rate": 0.4,
        "smart_wallets": 0, "kol_wallets": 0, "creation_timestamp": 1718500000,
        "is_honeypot": "no", "rug_ratio": 0.12, "buy_tax": 0.03, "sell_tax": 0.03,
        "open_source": "yes", "owner_renounced": "no", "burn_status": "",
    }


def test_build_entry_row_merges_and_derives():
    row = build_entry_row(_task(), _snapshot())
    assert row["task_id"] == "task-123"
    assert row["chain"] == "sol"
    assert row["base_market_cap"] == 500000
    assert row["turnover"] == 0.24
    assert round(row["avg_holding_usd"], 1) == 1562.5
    assert row["track_status"] == "tracking"
    assert row["gmgn_ok"] == 1


def test_build_entry_row_uses_backtest_performance_metrics():
    row = build_entry_row(_task(), _snapshot(), {
        "backtest_id": "bt-1",
        "base_market_cap": 600000,
        "peak_market_cap": 900000,
        "peak_gain_pct": 50.0,
        "max_drop_pct": 25.0,
        "settlement_market_cap": 450000,
        "settlement_gain_pct": -25.0,
        "status": "settled",
    })
    assert row["base_market_cap"] == 600000
    assert row["peak_market_cap"] == 900000
    assert row["peak_gain_pct"] == 50.0
    assert row["max_drop_pct"] == 25.0
    assert row["settlement_market_cap"] == 450000
    assert row["final_gain_pct"] == -25.0
    assert row["track_status"] == "done"
    assert row["smart_wallets"] == 0


def test_process_new_task_inserts(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    process_new_task(db, _task(), lambda chain, addr: _snapshot())
    assert db.exists("task-123")


def test_process_new_task_applies_backtest_fn(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    process_new_task(
        db,
        _task(),
        lambda chain, addr: _snapshot(),
        lambda chain, addr, pushed_at: {
            "backtest_id": "bt-1",
            "base_market_cap": 600000,
            "peak_market_cap": 900000,
            "peak_gain_pct": 50.0,
            "status": "tracking",
        },
    )
    row = db.get("task-123")
    assert row["backtest_id"] == "bt-1"
    assert row["base_market_cap"] == 600000
    assert row["peak_gain_pct"] == 50.0


def test_process_new_task_skips_existing(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    calls = {"n": 0}

    def snap(chain, addr):
        calls["n"] += 1
        return _snapshot()

    process_new_task(db, _task(), snap)
    process_new_task(db, _task(), snap)
    assert calls["n"] == 1


def test_refresh_one_updates_then_finalizes(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "t", "base_market_cap": 100.0,
                     "track_status": "tracking", "pushed_at": "2020-01-01T00:00:00Z"})
    # 过期（pushed 很久以前）→ finalize
    refresh_one(db, "t", lambda chain, addr: 130.0, track_hours=24, chain="sol", address="a")
    assert db.get("t")["track_status"] == "done"
    assert db.get("t")["final_gain_pct"] == 30.0


def test_refresh_one_does_not_finalize_backtest_controlled_rows(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.insert_entry({"task_id": "t", "base_market_cap": 100.0,
                     "track_status": "tracking", "backtest_id": "bt-1",
                     "current_gain_pct": -10.0,
                     "pushed_at": "2020-01-01T00:00:00Z"})
    refresh_one(db, "t", lambda chain, addr: 130.0, track_hours=24, chain="sol", address="a")
    row = db.get("t")
    assert row["track_status"] == "tracking"
    assert row["final_gain_pct"] is None
