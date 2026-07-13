"""Signal filtering: safety layer (hardcoded per-chain) + metric layer (operator-configurable).

Called before process_new_task. Returns (passes, filter_type, matched_rules).
- passes=True  → allow into analysis pipeline
- passes=False → caller writes filter_type + matched_rules to DB and stops processing

Config JSON schema (stored by signal_filter_store.py):
{
  "metric_filter_enabled": true,
  "metric_rules": [
    {
      "id": "r_xxx",
      "name": "集群机器人盘",
      "enabled": true,
      "conditions": [
        {"field": "bundler_rate", "op": ">=", "value": 60},
        {"field": "bot_degen_rate", "op": ">=", "value": 63}
      ]
    }
  ],
  "high_tax_threshold": 0.10
}

Operator-configurable metric fields store values in the units shown in the UI:
- percentages (top10_rate, bundler_rate, etc.): 0-100 scale
  (GMGN returns 0-1 floats; we multiply by 100 before comparing)
- absolute counts (smart_wallets, kol_wallets, holder_count): raw int
- dollar amounts (market_cap, liquidity, volume_24h, avg_holding_usd): raw float
- ratios/multiples (turnover_rate): raw float
- minutes (token_age_minutes): raw float
"""
from __future__ import annotations

import time
from typing import Optional


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

_SOL_CHAINS = {"sol", "solana"}
_EVM_CHAINS  = {"eth", "ethereum", "bsc", "bnb", "base"}


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _yn_yes(v) -> bool:
    """True when GMGN returns 'yes'/True/1 for a boolean field."""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("yes", "true", "1")


# ─────────────────────────────────────────────
# Safety layer (hardcoded, per-chain)
# ─────────────────────────────────────────────

def check_safety(chain: str, snap: dict, high_tax_threshold: float = 0.10) -> tuple[bool, list[str]]:
    """Return (passes, reasons). passes=False means safety-filtered."""
    c = (chain or "").lower()
    reasons: list[str] = []

    if c in _SOL_CHAINS:
        if snap.get("renounced_mint") == "no":
            reasons.append("铸币权未放弃")
        if snap.get("renounced_freeze") == "no":
            reasons.append("冻结权未放弃")
        if snap.get("can_not_sell") == 1:
            reasons.append("代币无法卖出")
        rug = _f(snap.get("rug_ratio"))
        if rug is not None and rug > 0.3:
            reasons.append(f"rug风险={rug:.0%}")

    elif c in _EVM_CHAINS:
        if _yn_yes(snap.get("is_honeypot")):
            reasons.append("蜜罐合约")
        if snap.get("can_not_sell") == 1:
            reasons.append("代币无法卖出")
        if _yn_yes(snap.get("is_blacklist")):
            reasons.append("黑名单后门")
        rug = _f(snap.get("rug_ratio"))
        if rug is not None and rug > 0.3:
            reasons.append(f"rug风险={rug:.0%}")
        # high tax (EVM only, operator-configurable threshold)
        buy_tax  = _f(snap.get("buy_tax"))
        sell_tax = _f(snap.get("sell_tax"))
        worst = max(t for t in (buy_tax, sell_tax) if t is not None) if any(
            t is not None for t in (buy_tax, sell_tax)
        ) else None
        if worst is not None and worst > high_tax_threshold:
            reasons.append(f"高税率={worst:.0%}")

    return (len(reasons) == 0), reasons


# ─────────────────────────────────────────────
# Derived metrics for operator rules
# ─────────────────────────────────────────────

def _build_metric_row(snap: dict, chain: str = "") -> dict:
    """Flatten snap into the 16 operator-visible metric fields (UI unit scale)."""
    mc       = _f(snap.get("market_cap"))
    vol      = _f(snap.get("volume_24h"))
    holders  = _f(snap.get("holder_count"))
    creation = _f(snap.get("creation_timestamp"))

    turnover    = (vol / mc) if (vol is not None and mc) else None
    avg_holding = (mc / holders) if (mc is not None and holders) else None
    token_age   = ((time.time() - creation) / 60) if creation else None  # minutes

    def pct(v) -> Optional[float]:
        """Convert 0-1 fraction → 0-100 percentage for UI-scale comparison."""
        f = _f(v)
        return f * 100 if f is not None else None

    return {
        "market_cap":        mc,
        "liquidity":         _f(snap.get("liquidity")),
        "volume_24h":        vol,
        "turnover_rate":     turnover,
        "holder_count":      _f(snap.get("holder_count")),
        "avg_holding":       avg_holding,
        "top10_rate":        pct(snap.get("top10_rate")),
        "dev_hold_rate":     pct(snap.get("dev_hold_rate")),
        "bundler_rate":      pct(snap.get("bundler_rate")),
        "bot_degen_rate":    pct(snap.get("bot_degen_rate")),
        "entrapment_rate":   pct(snap.get("entrapment_rate")),
        "rat_rate":          pct(snap.get("rat_rate")),
        "fresh_wallet_rate": pct(snap.get("fresh_wallet_rate")),
        "smart_wallets":     _f(snap.get("smart_wallets")),
        "kol_wallets":       _f(snap.get("kol_wallets")),
        "token_age_minutes": token_age,
    }


# ─────────────────────────────────────────────
# Metric layer (operator rules)
# ─────────────────────────────────────────────

def _eval_condition(row_val: Optional[float], op: str, value: float, value2: Optional[float] = None) -> bool:
    """Evaluate a single condition. Missing field → passes (per §8 on_missing_field=pass)."""
    if row_val is None:
        return False  # can't determine → pass (caller treats False as "condition not matched")
    if op == ">=":
        return row_val >= value
    if op == "<=":
        return row_val <= value
    if op == ">":
        return row_val > value
    if op == "<":
        return row_val < value
    if op == "==":
        return row_val == value
    if op == "between":
        hi = value2 if value2 is not None else value
        return value <= row_val <= hi
    return False


def _eval_condition_safe(row_val: Optional[float], op: str, value: float, value2: Optional[float] = None) -> Optional[bool]:
    """None = field missing (treated as pass-through per spec)."""
    if row_val is None:
        return None
    return _eval_condition(row_val, op, value, value2)


def check_metrics(metric_row: dict, config: dict) -> tuple[bool, list[str]]:
    """
    Evaluate operator metric rules.
    Returns (passes, matched_rule_names).
    passes=False when any enabled rule fires (all its conditions AND-match).
    """
    if not config.get("metric_filter_enabled", False):
        return True, []

    rules = config.get("metric_rules") or []
    matched: list[str] = []

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        conditions = rule.get("conditions") or []
        if not conditions:
            continue

        rule_hit = True
        for cond in conditions:
            field  = cond.get("field", "")
            op     = cond.get("op", ">=")
            value  = float(cond.get("value", 0))
            value2 = float(cond["value2"]) if cond.get("value2") is not None else None

            row_val = metric_row.get(field)
            result  = _eval_condition_safe(row_val, op, value, value2)
            if result is None:
                # Missing field → treat this condition as NOT matching (pass-through)
                rule_hit = False
                break
            if not result:
                rule_hit = False
                break

        if rule_hit:
            matched.append(rule.get("name") or rule.get("id") or "unknown")

    return (len(matched) == 0), matched


# ─────────────────────────────────────────────
# Combined entry point
# ─────────────────────────────────────────────

def run_filter(
    chain: str,
    snap: dict,
    config: dict,
) -> tuple[bool, Optional[str], list[str]]:
    """
    Run safety + metric layers.

    Returns (passes, filter_type, matched_rules):
      passes=True  → token passes, proceed to analysis
      passes=False → filter_type is 'safety' or 'metric', matched_rules is non-empty

    If GMGN fetch failed (gmgn_ok=False), skip filtering and pass through.
    """
    if not snap.get("gmgn_ok"):
        return True, None, []

    # 1. Safety layer
    high_tax = float(config.get("high_tax_threshold", 0.10))
    safety_ok, safety_reasons = check_safety(chain, snap, high_tax)
    if not safety_ok:
        return False, "safety", safety_reasons

    # 2. Metric layer
    metric_row = _build_metric_row(snap, chain)
    metric_ok, metric_rules = check_metrics(metric_row, config)
    if not metric_ok:
        return False, "metric", metric_rules

    return True, None, []
