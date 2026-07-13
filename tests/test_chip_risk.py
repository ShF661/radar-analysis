"""Unit tests for chip_risk.py — compute_chip_risk and chip_risk_summary."""
from __future__ import annotations

import pytest
from app.chip_risk import compute_chip_risk, chip_risk_summary


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _row(**kwargs) -> dict:
    """Minimal clean row — all indicators below threshold, gmgn_ok=1."""
    base = {
        "gmgn_ok": 1,
        "entrapment_rate": 0.05,   # <0.15
        "bundler_rate":    0.20,   # <0.40
        "dev_hold_rate":   0.10,   # <0.20
        "fresh_wallet_rate": 0.10, # <0.20
        "top10_rate":      0.30,   # <0.50
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────
# gmgn_ok guard
# ─────────────────────────────────────────────

def test_gmgn_not_ok_returns_empty():
    row = _row(gmgn_ok=0, entrapment_rate=0.99)
    assert compute_chip_risk(row) == []


def test_gmgn_ok_none_returns_empty():
    row = _row(gmgn_ok=None, bundler_rate=0.99)
    assert compute_chip_risk(row) == []


def test_gmgn_ok_false_returns_empty():
    row = _row(gmgn_ok=False, dev_hold_rate=0.99)
    assert compute_chip_risk(row) == []


# ─────────────────────────────────────────────
# Clean token — no warnings
# ─────────────────────────────────────────────

def test_clean_row_no_warnings():
    assert compute_chip_risk(_row()) == []


# ─────────────────────────────────────────────
# Each indicator fires independently
# ─────────────────────────────────────────────

def test_entrapment_rate_fires():
    row = _row(entrapment_rate=0.15)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 1
    assert "钓鱼钱包" in warnings[0]
    assert "15%" in warnings[0]


def test_entrapment_rate_below_threshold_passes():
    row = _row(entrapment_rate=0.149)
    assert compute_chip_risk(row) == []


def test_bundler_rate_fires():
    row = _row(bundler_rate=0.40)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 1
    assert "集群/捆绑" in warnings[0]
    assert "40%" in warnings[0]


def test_bundler_rate_below_threshold_passes():
    row = _row(bundler_rate=0.399)
    assert compute_chip_risk(row) == []


def test_dev_hold_rate_fires():
    row = _row(dev_hold_rate=0.20)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 1
    assert "DEV 持仓" in warnings[0]


def test_fresh_wallet_rate_fires():
    row = _row(fresh_wallet_rate=0.20)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 1
    assert "新钱包" in warnings[0]


def test_top10_rate_fires():
    row = _row(top10_rate=0.50)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 1
    assert "Top10 持仓" in warnings[0]


def test_top10_rate_below_threshold_passes():
    row = _row(top10_rate=0.499)
    assert compute_chip_risk(row) == []


# ─────────────────────────────────────────────
# Multiple indicators
# ─────────────────────────────────────────────

def test_two_indicators_both_returned():
    row = _row(bundler_rate=0.42, dev_hold_rate=0.25)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 2
    labels = " ".join(warnings)
    assert "集群/捆绑" in labels
    assert "DEV 持仓" in labels


def test_three_indicators_all_returned():
    row = _row(entrapment_rate=0.20, bundler_rate=0.50, dev_hold_rate=0.30)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 3


def test_four_indicators_capped_at_three():
    row = _row(entrapment_rate=0.20, bundler_rate=0.50,
               dev_hold_rate=0.30, fresh_wallet_rate=0.25)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 3


def test_five_indicators_capped_at_three():
    row = _row(entrapment_rate=0.20, bundler_rate=0.50, dev_hold_rate=0.30,
               fresh_wallet_rate=0.25, top10_rate=0.55)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 3


# ─────────────────────────────────────────────
# Priority ordering (cap at 3 uses highest priority first)
# ─────────────────────────────────────────────

def test_priority_order_entrapment_first():
    # All 5 fire; top 3 by priority = entrapment > bundler > dev
    row = _row(entrapment_rate=0.20, bundler_rate=0.50, dev_hold_rate=0.30,
               fresh_wallet_rate=0.25, top10_rate=0.55)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 3
    assert "钓鱼钱包" in warnings[0]
    assert "集群/捆绑" in warnings[1]
    assert "DEV 持仓" in warnings[2]


def test_priority_order_without_entrapment():
    # entrapment clean; 4 fire → top 3 = bundler > dev > fresh
    row = _row(bundler_rate=0.50, dev_hold_rate=0.30,
               fresh_wallet_rate=0.25, top10_rate=0.55)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 3
    assert "集群/捆绑" in warnings[0]
    assert "DEV 持仓" in warnings[1]
    assert "新钱包" in warnings[2]


# ─────────────────────────────────────────────
# Missing / None fields treated as pass-through
# ─────────────────────────────────────────────

def test_missing_field_skipped():
    row = {"gmgn_ok": 1}  # none of the indicator fields present
    assert compute_chip_risk(row) == []


def test_none_field_skipped():
    row = _row(bundler_rate=None)
    # bundler missing → only checks remaining; others below threshold
    assert compute_chip_risk(row) == []


def test_non_numeric_field_skipped():
    row = _row(bundler_rate="invalid_string")
    assert compute_chip_risk(row) == []


def test_gmgn_ok_string_truthy():
    # gmgn_ok stored as string "1" — still truthy, should fire
    row = _row(gmgn_ok="1", bundler_rate=0.50)
    warnings = compute_chip_risk(row)
    assert len(warnings) == 1
    assert "集群/捆绑" in warnings[0]


def test_negative_indicator_value():
    # negative value is below threshold — should not fire
    row = _row(bundler_rate=-0.50)
    assert compute_chip_risk(row) == []


# ─────────────────────────────────────────────
# Warning line format
# ─────────────────────────────────────────────

def test_warning_line_format():
    row = _row(bundler_rate=0.423)
    warnings = compute_chip_risk(row)
    assert warnings[0] == "🚨 筹码异常 · 注意暴跌风险：集群/捆绑 42%"


def test_warning_line_rounding():
    row = _row(top10_rate=0.556)  # rounds to 56%
    warnings = compute_chip_risk(row)
    assert "56%" in warnings[0]


def test_warning_line_rounding_half_up():
    # 0.425 * 100 = 42.5 — must round up to 43% (not banker's rounding 42%)
    row = _row(bundler_rate=0.425)
    warnings = compute_chip_risk(row)
    assert "43%" in warnings[0]


def test_warning_line_rounding_half_up_odd():
    # 0.415 * 100 = 41.5 — must round up to 42%
    row = _row(bundler_rate=0.415)
    warnings = compute_chip_risk(row)
    assert "42%" in warnings[0]


# ─────────────────────────────────────────────
# chip_risk_summary
# ─────────────────────────────────────────────

def test_summary_no_warnings():
    result = chip_risk_summary(_row())
    assert result["warnings"] == []
    assert result["triggered_count"] == 0
    assert "raw" in result
    assert result["raw"]["bundler_rate"] == pytest.approx(0.20)


def test_summary_with_warning():
    result = chip_risk_summary(_row(entrapment_rate=0.18))
    assert result["triggered_count"] == 1
    assert len(result["warnings"]) == 1
    assert result["raw"]["entrapment_rate"] == pytest.approx(0.18)


def test_summary_missing_fields_raw_is_none():
    result = chip_risk_summary({"gmgn_ok": 1})
    assert result["raw"]["bundler_rate"] is None
    assert result["raw"]["top10_rate"] is None
    assert result["triggered_count"] == 0


def test_summary_gmgn_not_ok_no_warnings_but_raw_present():
    result = chip_risk_summary(_row(gmgn_ok=0, bundler_rate=0.90))
    assert result["warnings"] == []
    assert result["triggered_count"] == 0
    assert result["raw"]["bundler_rate"] == pytest.approx(0.90)


# ─────────────────────────────────────────────
# API endpoint integration
# ─────────────────────────────────────────────

from pathlib import Path
from fastapi.testclient import TestClient
from app.api import create_app
from app.db import Database


def _db(tmp_path) -> Database:
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    return db


def test_api_chip_risk_404_on_missing(tmp_path):
    db = _db(tmp_path)
    c = TestClient(create_app(db, db_path=str(tmp_path / "t.db")))
    r = c.get("/api/v1/tokens/nonexistent/chip-risk")
    assert r.status_code == 404


def test_api_chip_risk_clean_token(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({
        "task_id": "t1", "chain": "sol", "track_status": "tracking",
        "gmgn_ok": 1,
        "entrapment_rate": 0.05, "bundler_rate": 0.20,
        "dev_hold_rate": 0.10, "fresh_wallet_rate": 0.10, "top10_rate": 0.30,
    })
    c = TestClient(create_app(db, db_path=str(tmp_path / "t.db")))
    r = c.get("/api/v1/tokens/t1/chip-risk")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == "t1"
    assert body["warnings"] == []
    assert body["triggered_count"] == 0


def test_api_chip_risk_fires_warning(tmp_path):
    db = _db(tmp_path)
    db.insert_entry({
        "task_id": "t1", "chain": "sol", "track_status": "tracking",
        "gmgn_ok": 1,
        "entrapment_rate": 0.05, "bundler_rate": 0.45,  # bundler fires
        "dev_hold_rate": 0.10, "fresh_wallet_rate": 0.10, "top10_rate": 0.30,
    })
    c = TestClient(create_app(db, db_path=str(tmp_path / "t.db")))
    r = c.get("/api/v1/tokens/t1/chip-risk")
    assert r.status_code == 200
    body = r.json()
    assert body["triggered_count"] == 1
    assert "集群/捆绑" in body["warnings"][0]
    assert "45%" in body["warnings"][0]
