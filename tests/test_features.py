from app.features import derive_metrics, DEFAULT_THRESHOLDS, FEATURE_LABELS


def test_derive_metrics_turnover_and_avg_holding():
    m = derive_metrics({"volume_24h": 120000, "market_cap": 500000, "holder_count": 320})
    assert m["turnover"] == 0.24                  # 120000/500000
    assert round(m["avg_holding_usd"], 2) == 1562.50  # 500000/320


def test_derive_metrics_safe_on_missing():
    m = derive_metrics({"volume_24h": None, "market_cap": 0, "holder_count": 0})
    assert m["turnover"] is None
    assert m["avg_holding_usd"] is None


def test_thresholds_have_labels():
    # 阈值键都应有中文名（前端阈值编辑器用得到）
    for key in DEFAULT_THRESHOLDS:
        assert key in FEATURE_LABELS
