from __future__ import annotations

from typing import Optional

from app.features import FEATURE_LABELS, derive_features

DEFAULT_GAIN_BUCKETS = [
    {"label": "<50%", "min": None, "max": 50},
    {"label": "50–100%", "min": 50, "max": 100},
    {"label": ">100%", "min": 100, "max": None},
]

DEFAULT_DROP_BUCKETS = [
    {"label": "跌<30%", "min": 0, "max": 30},
    {"label": "跌30–50%", "min": 30, "max": 50},
    {"label": "跌50–80%", "min": 50, "max": 80},
    {"label": "跌>80%", "min": 80, "max": None},
]


def assign_bucket(value: Optional[float], buckets: list[dict]) -> Optional[str]:
    if value is None:
        return None
    for b in buckets:
        lo = b["min"]
        hi = b["max"]
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return b["label"]
    return None


def _rate(rows: list[dict], feature: str, feats: dict) -> Optional[float]:
    vals = [feats[r["task_id"]][feature] for r in rows if feats[r["task_id"]][feature] is not None]
    if not vals:
        return None
    return sum(1 for v in vals if v) / len(vals)


def cohort_analysis(rows: list[dict], dimension: str, buckets: list[dict], thresholds: dict) -> dict:
    feats = {r["task_id"]: derive_features(r, thresholds) for r in rows}
    dim_rows = [r for r in rows if r.get(dimension) is not None]
    total = len(dim_rows)
    baseline = {k: _rate(dim_rows, k, feats) for k in FEATURE_LABELS}

    out_buckets = []
    for b in buckets:
        members = [r for r in dim_rows if assign_bucket(r.get(dimension), [b]) == b["label"]]
        feat_stats = []
        for k in FEATURE_LABELS:
            br = _rate(members, k, feats)
            base = baseline.get(k)
            if br is None:
                continue
            lift = (br - base) if base is not None else 0.0
            feat_stats.append({
                "feature": k, "label": FEATURE_LABELS[k],
                "bucket_rate": br, "baseline_rate": base, "lift": lift,
            })
        feat_stats.sort(key=lambda x: x["lift"], reverse=True)
        out_buckets.append({
            "label": b["label"],
            "count": len(members),
            "pct_of_total": (len(members) / total) if total else 0.0,
            "tokens": [
                {"task_id": r["task_id"], "symbol": r.get("symbol"),
                 "address": r.get("address"), "value": r.get(dimension)}
                for r in members
            ],
            "features": feat_stats,
        })
    return {"dimension": dimension, "total": total, "baseline": baseline, "buckets": out_buckets}
