"""Tests for signal_filter.py — safety layer, metric layer, and combined run_filter."""
from __future__ import annotations

import pytest
from app.signal_filter import (
    check_safety,
    check_metrics,
    run_filter,
    _build_metric_row,
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _sol_snap(**kwargs):
    base = {
        "gmgn_ok": True,
        "renounced_mint": "yes",
        "renounced_freeze": "yes",
        "can_not_sell": 0,
        "rug_ratio": 0.1,
        # market metric fields
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
    base.update(kwargs)
    return base


def _evm_snap(**kwargs):
    base = {
        "gmgn_ok": True,
        "is_honeypot": "no",
        "can_not_sell": 0,
        "is_blacklist": "no",
        "rug_ratio": 0.1,
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
    base.update(kwargs)
    return base


def _config(enabled=True, rules=None, high_tax=0.10):
    return {
        "metric_filter_enabled": enabled,
        "metric_rules": rules or [],
        "high_tax_threshold": high_tax,
    }


def _rule(name="test", conditions=None, enabled=True):
    return {
        "id": "r_test",
        "name": name,
        "enabled": enabled,
        "conditions": conditions or [],
    }


# ─────────────────────────────────────────────
# Safety layer — SOL
# ─────────────────────────────────────────────

def test_sol_clean_passes():
    ok, reasons = check_safety("sol", _sol_snap())
    assert ok
    assert reasons == []


def test_sol_mint_not_renounced():
    ok, reasons = check_safety("sol", _sol_snap(renounced_mint="no"))
    assert not ok
    assert any("铸币权" in r for r in reasons)


def test_sol_freeze_not_renounced():
    ok, reasons = check_safety("sol", _sol_snap(renounced_freeze="no"))
    assert not ok
    assert any("冻结权" in r for r in reasons)


def test_sol_can_not_sell():
    ok, reasons = check_safety("sol", _sol_snap(can_not_sell=1))
    assert not ok
    assert any("无法卖出" in r for r in reasons)


def test_sol_high_rug():
    ok, reasons = check_safety("sol", _sol_snap(rug_ratio=0.31))
    assert not ok
    assert any("rug" in r for r in reasons)


def test_sol_rug_at_threshold_passes():
    # exactly 0.3 → passes (threshold is >0.3)
    ok, _ = check_safety("sol", _sol_snap(rug_ratio=0.30))
    assert ok


# SOL-only fields don't fire on wrong chain
def test_sol_fields_ignored_on_evm():
    snap = _evm_snap(renounced_mint="no", renounced_freeze="no")
    ok, reasons = check_safety("eth", snap)
    assert ok
    assert reasons == []


# ─────────────────────────────────────────────
# Safety layer — EVM
# ─────────────────────────────────────────────

def test_evm_clean_passes():
    ok, reasons = check_safety("bsc", _evm_snap())
    assert ok
    assert reasons == []


def test_evm_honeypot():
    ok, reasons = check_safety("eth", _evm_snap(is_honeypot="yes"))
    assert not ok
    assert any("蜜罐" in r for r in reasons)


def test_evm_can_not_sell():
    ok, reasons = check_safety("base", _evm_snap(can_not_sell=1))
    assert not ok


def test_evm_blacklist():
    ok, reasons = check_safety("bsc", _evm_snap(is_blacklist="yes"))
    assert not ok
    assert any("黑名单" in r for r in reasons)


def test_evm_high_rug():
    ok, reasons = check_safety("eth", _evm_snap(rug_ratio=0.5))
    assert not ok


def test_evm_high_buy_tax():
    ok, reasons = check_safety("eth", _evm_snap(buy_tax=0.15, sell_tax=0.03))
    assert not ok
    assert any("税率" in r for r in reasons)


def test_evm_high_sell_tax():
    ok, reasons = check_safety("eth", _evm_snap(buy_tax=0.03, sell_tax=0.12))
    assert not ok


def test_evm_tax_exactly_at_threshold_passes():
    # exactly 10% → passes (threshold is >0.10)
    ok, _ = check_safety("eth", _evm_snap(buy_tax=0.10, sell_tax=0.10))
    assert ok


def test_evm_custom_tax_threshold():
    ok, _ = check_safety("eth", _evm_snap(buy_tax=0.08), high_tax_threshold=0.05)
    assert not ok


# ─────────────────────────────────────────────
# Metric row builder
# ─────────────────────────────────────────────

def test_metric_row_pct_conversion():
    snap = _sol_snap(bundler_rate=0.35, top10_rate=0.42)
    row = _build_metric_row(snap)
    assert abs(row["bundler_rate"] - 35.0) < 0.01
    assert abs(row["top10_rate"] - 42.0) < 0.01


def test_metric_row_turnover():
    snap = _sol_snap(market_cap=500_000, volume_24h=250_000)
    row = _build_metric_row(snap)
    assert abs(row["turnover_rate"] - 0.5) < 0.001


def test_metric_row_avg_holding():
    snap = _sol_snap(market_cap=400_000, holder_count=200)
    row = _build_metric_row(snap)
    assert abs(row["avg_holding"] - 2000.0) < 0.01


def test_metric_row_missing_fields_are_none():
    snap = {"gmgn_ok": True}
    row = _build_metric_row(snap)
    assert row["market_cap"] is None
    assert row["turnover_rate"] is None
    assert row["token_age_minutes"] is None


# ─────────────────────────────────────────────
# Metric layer
# ─────────────────────────────────────────────

def test_metric_disabled_always_passes():
    cfg = _config(enabled=False, rules=[
        _rule(conditions=[{"field": "bundler_rate", "op": ">=", "value": 1}])
    ])
    snap = _sol_snap(bundler_rate=0.99)
    row = _build_metric_row(snap)
    ok, matched = check_metrics(row, cfg)
    assert ok


def test_metric_no_rules_passes():
    cfg = _config(enabled=True, rules=[])
    row = _build_metric_row(_sol_snap())
    ok, matched = check_metrics(row, cfg)
    assert ok


def test_metric_single_condition_hit():
    cfg = _config(rules=[
        _rule("高集群", [{"field": "bundler_rate", "op": ">=", "value": 60}])
    ])
    snap = _sol_snap(bundler_rate=0.65)  # 65% > 60
    row = _build_metric_row(snap)
    ok, matched = check_metrics(row, cfg)
    assert not ok
    assert matched == ["高集群"]


def test_metric_single_condition_miss():
    cfg = _config(rules=[
        _rule("高集群", [{"field": "bundler_rate", "op": ">=", "value": 60}])
    ])
    snap = _sol_snap(bundler_rate=0.40)  # 40% < 60
    row = _build_metric_row(snap)
    ok, matched = check_metrics(row, cfg)
    assert ok


def test_metric_and_within_rule():
    # Both conditions must match → AND
    cfg = _config(rules=[
        _rule("集群+机器人", [
            {"field": "bundler_rate",   "op": ">=", "value": 60},
            {"field": "bot_degen_rate", "op": ">=", "value": 50},
        ])
    ])
    # Only bundler high, bot not
    snap = _sol_snap(bundler_rate=0.65, bot_degen_rate=0.30)
    row = _build_metric_row(snap)
    ok, _ = check_metrics(row, cfg)
    assert ok  # bot_degen_rate=30% < 50, so rule does NOT fire

    # Both high
    snap2 = _sol_snap(bundler_rate=0.65, bot_degen_rate=0.55)
    row2 = _build_metric_row(snap2)
    ok2, matched = check_metrics(row2, cfg)
    assert not ok2
    assert "集群+机器人" in matched


def test_metric_or_between_rules():
    # Rule A OR Rule B → either firing blocks
    cfg = _config(rules=[
        _rule("rule_a", [{"field": "bundler_rate", "op": ">=", "value": 60}]),
        _rule("rule_b", [{"field": "kol_wallets",  "op": "==", "value": 0}]),
    ])
    # Only rule_b fires (kol=0)
    snap = _sol_snap(bundler_rate=0.20, kol_wallets=0)
    row = _build_metric_row(snap)
    ok, matched = check_metrics(row, cfg)
    assert not ok
    assert "rule_b" in matched


def test_metric_disabled_rule_skipped():
    cfg = _config(rules=[
        _rule("disabled", [{"field": "bundler_rate", "op": ">=", "value": 1}], enabled=False)
    ])
    snap = _sol_snap(bundler_rate=0.99)
    row = _build_metric_row(snap)
    ok, _ = check_metrics(row, cfg)
    assert ok  # rule disabled, should not fire


def test_metric_missing_field_passes_condition():
    # snap has no smart_wallets → field is None → condition is skipped (pass-through)
    cfg = _config(rules=[
        _rule("no_smart", [{"field": "smart_wallets", "op": "==", "value": 0}])
    ])
    snap = {"gmgn_ok": True}  # missing smart_wallets
    row = _build_metric_row(snap)
    ok, _ = check_metrics(row, cfg)
    assert ok


def test_metric_between_op():
    cfg = _config(rules=[
        _rule("mid_mc", [{"field": "market_cap", "op": "between", "value": 100_000, "value2": 500_000}])
    ])
    snap = _sol_snap(market_cap=300_000)
    row = _build_metric_row(snap)
    ok, matched = check_metrics(row, cfg)
    assert not ok

    snap2 = _sol_snap(market_cap=50_000)
    row2 = _build_metric_row(snap2)
    ok2, _ = check_metrics(row2, cfg)
    assert ok2


# ─────────────────────────────────────────────
# Combined run_filter
# ─────────────────────────────────────────────

def test_run_filter_gmgn_fail_passes():
    snap = _sol_snap(gmgn_ok=False, renounced_mint="no")  # would fail safety if gmgn_ok
    cfg = _config()
    passes, ft, rules = run_filter("sol", snap, cfg)
    assert passes
    assert ft is None


def test_run_filter_safety_blocks():
    snap = _sol_snap(renounced_mint="no")
    cfg = _config()
    passes, ft, rules = run_filter("sol", snap, cfg)
    assert not passes
    assert ft == "safety"
    assert len(rules) > 0


def test_run_filter_metric_blocks():
    snap = _sol_snap(bundler_rate=0.70, bot_degen_rate=0.65)
    cfg = _config(rules=[
        _rule("集群机器人", [
            {"field": "bundler_rate",   "op": ">=", "value": 60},
            {"field": "bot_degen_rate", "op": ">=", "value": 60},
        ])
    ])
    passes, ft, rules = run_filter("sol", snap, cfg)
    assert not passes
    assert ft == "metric"
    assert "集群机器人" in rules


def test_run_filter_safety_checked_before_metric():
    # Snap fails safety; metric rule also configured
    snap = _evm_snap(is_honeypot="yes", bundler_rate=0.70)
    cfg = _config(rules=[
        _rule("集群", [{"field": "bundler_rate", "op": ">=", "value": 60}])
    ])
    passes, ft, rules = run_filter("eth", snap, cfg)
    assert not passes
    assert ft == "safety"  # safety fires first


def test_run_filter_clean_token_passes_all():
    snap = _sol_snap()
    cfg = _config(rules=[
        _rule("高集群", [{"field": "bundler_rate", "op": ">=", "value": 90}])
    ])
    passes, ft, rules = run_filter("sol", snap, cfg)
    assert passes
    assert ft is None
    assert rules == []
