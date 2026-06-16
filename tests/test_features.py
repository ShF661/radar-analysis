from app.features import derive_metrics, derive_features, DEFAULT_THRESHOLDS, FEATURE_LABELS


def test_derive_metrics_turnover_and_avg_holding():
    m = derive_metrics({"volume_24h": 120000, "market_cap": 500000, "holder_count": 320})
    assert m["turnover"] == 0.24                  # 120000/500000
    assert round(m["avg_holding_usd"], 2) == 1562.50  # 500000/320


def test_derive_metrics_safe_on_missing():
    m = derive_metrics({"volume_24h": None, "market_cap": 0, "holder_count": 0})
    assert m["turnover"] is None
    assert m["avg_holding_usd"] is None


def test_derive_features_flags():
    row = {
        "smart_wallets": 0, "kol_wallets": 0, "bundler_rate": 0.35,
        "fresh_wallet_rate": 0.55, "rat_rate": 0.12, "top10_rate": 0.42,
        "dev_hold_rate": 0.06, "bot_degen_rate": 0.4, "turnover": 0.24,
        "liquidity": 25000, "is_honeypot": "no", "open_source": "yes",
        "owner_renounced": "no", "rug_ratio": 0.12, "entrapment_rate": 0.08,
        "holder_count": 320, "buy_tax": 0.03, "sell_tax": 0.03,
    }
    f = derive_features(row, DEFAULT_THRESHOLDS)
    assert f["smart_money_zero"] is True
    assert f["kol_zero"] is True
    assert f["high_bundler"] is True       # 0.35 > 0.30
    assert f["high_fresh"] is True         # 0.55 > 0.50
    assert f["not_renounced"] is True
    assert f["honeypot"] is False
    assert f["has_tax"] is True


def test_derive_features_none_when_missing():
    f = derive_features({"smart_wallets": None}, DEFAULT_THRESHOLDS)
    assert f["smart_money_zero"] is None


def test_every_feature_has_label():
    f = derive_features({}, DEFAULT_THRESHOLDS)
    for key in f:
        assert key in FEATURE_LABELS
