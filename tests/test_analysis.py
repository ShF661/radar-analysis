from app.analysis import assign_bucket, cohort_analysis, DEFAULT_GAIN_BUCKETS, DEFAULT_DROP_BUCKETS
from app.features import DEFAULT_THRESHOLDS


def test_assign_bucket_ranges():
    b = [{"label": "<50%", "min": None, "max": 50}, {"label": ">=50%", "min": 50, "max": None}]
    assert assign_bucket(10, b) == "<50%"
    assert assign_bucket(50, b) == ">=50%"
    assert assign_bucket(None, b) is None


def test_cohort_analysis_proportions_and_lift():
    # 4 个无涨幅币聪明钱都为 0；2 个高涨幅币聪明钱非 0
    rows = []
    for i in range(4):
        rows.append({"task_id": f"low{i}", "symbol": "L", "address": f"a{i}",
                     "peak_gain_pct": 10, "smart_wallets": 0})
    for i in range(2):
        rows.append({"task_id": f"hi{i}", "symbol": "H", "address": f"b{i}",
                     "peak_gain_pct": 200, "smart_wallets": 3})
    out = cohort_analysis(rows, "peak_gain_pct", DEFAULT_GAIN_BUCKETS, DEFAULT_THRESHOLDS)
    low = next(b for b in out["buckets"] if b["label"] == "<50%")
    assert low["count"] == 4
    smz = next(f for f in low["features"] if f["feature"] == "smart_money_zero")
    assert smz["bucket_rate"] == 1.0          # 4/4
    assert round(smz["baseline_rate"], 3) == round(4 / 6, 3)
    assert smz["lift"] > 0
    # 特征按 lift 降序
    lifts = [f["lift"] for f in low["features"]]
    assert lifts == sorted(lifts, reverse=True)


def test_cohort_lists_tokens_per_bucket():
    rows = [{"task_id": "x", "symbol": "X", "address": "ax", "peak_gain_pct": 300, "smart_wallets": 1}]
    out = cohort_analysis(rows, "peak_gain_pct", DEFAULT_GAIN_BUCKETS, DEFAULT_THRESHOLDS)
    hi = next(b for b in out["buckets"] if b["label"] == ">100%")
    assert hi["tokens"][0]["task_id"] == "x"
    assert hi["pct_of_total"] == 1.0
