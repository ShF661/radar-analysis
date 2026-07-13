"""筹码异常风险提醒 — 检测逻辑。

Five indicators, any one triggers a warning line.
Fields in radar.db are stored at GMGN scale (0-1 for rates);
thresholds here use the same scale so no conversion is needed.

Priority order (for capping at 3 when ≥4 fire):
  entrapment_rate > bundler_rate > dev_hold_rate > fresh_wallet_rate > top10_rate
"""
from __future__ import annotations

from typing import Optional

# (field_name_in_db, display_label, threshold, priority)
# threshold is in GMGN scale (0-1); top10_rate stored same way.
_INDICATORS: list[tuple[str, str, float, int]] = [
    ("entrapment_rate", "钓鱼钱包", 0.15, 0),   # ≥15% → priority 0 (highest)
    ("bundler_rate",    "集群/捆绑", 0.40, 1),   # ≥40%
    ("dev_hold_rate",   "DEV 持仓",  0.20, 2),   # ≥20%
    ("fresh_wallet_rate", "新钱包",  0.20, 3),   # ≥20%
    ("top10_rate",      "Top10 持仓", 0.50, 4),  # ≥50%
]

_MAX_LINES = 3


def compute_chip_risk(row: dict) -> list[str]:
    """Return up to _MAX_LINES warning strings for a token row.

    row should be a dict from db.get() — fields stored in GMGN scale (0-1).
    Returns [] when no indicator fires or when gmgn_ok is falsy.
    """
    if not row.get("gmgn_ok"):
        return []

    fired: list[tuple[int, str, float]] = []  # (priority, label, value)
    for field, label, threshold, priority in _INDICATORS:
        val = row.get(field)
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if fval >= threshold:
            fired.append((priority, label, fval))

    if not fired:
        return []

    # Sort by priority (lower = more important), cap at _MAX_LINES.
    fired.sort(key=lambda x: x[0])
    lines = []
    for _, label, fval in fired[:_MAX_LINES]:
        pct = int(fval * 100 + 0.5)  # round half-up, avoids banker's rounding
        lines.append(f"🚨 筹码异常 · 注意暴跌风险：{label} {pct}%")
    return lines


def chip_risk_summary(row: dict) -> dict:
    """Return the full chip risk payload for the API endpoint."""
    warnings = compute_chip_risk(row)
    raw: dict[str, Optional[float]] = {}
    for field, _label, _threshold, _priority in _INDICATORS:
        val = row.get(field)
        raw[field] = float(val) if val is not None else None
    return {
        "warnings": warnings,
        "triggered_count": len(warnings),
        "raw": raw,
    }
