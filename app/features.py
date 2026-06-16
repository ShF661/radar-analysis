from __future__ import annotations

from typing import Optional

DEFAULT_THRESHOLDS = {
    "high_bundler": 0.30,
    "high_fresh": 0.50,
    "high_rat": 0.10,
    "high_top10": 0.30,
    "high_dev": 0.05,
    "high_bot": 0.30,
    "low_turnover": 1.0,
    "low_liquidity": 10000,
    "high_rug": 0.30,
    "high_entrapment": 0.10,
    "low_holders": 100,
}

FEATURE_LABELS = {
    "smart_money_zero": "聪明钱买入 = 0",
    "kol_zero": "KOL 买入 = 0",
    "high_bundler": "集群钱包占比高",
    "high_fresh": "新钱包占比高",
    "high_rat": "老鼠仓占比高",
    "high_top10": "TOP10 持仓集中",
    "high_dev": "DEV 持仓偏高",
    "high_bot": "机器人交易占比高",
    "low_turnover": "换手率低",
    "low_liquidity": "流动性低",
    "high_rug": "rug 风险高",
    "high_entrapment": "钓鱼钱包占比高",
    "low_holders": "持有人少",
    "honeypot": "蜜罐",
    "not_open_source": "合约未开源",
    "not_renounced": "未弃权",
    "has_tax": "有买卖税",
}


def derive_metrics(row: dict) -> dict:
    vol = row.get("volume_24h")
    mc = row.get("market_cap")
    hc = row.get("holder_count")
    turnover = (vol / mc) if (vol is not None and mc) else None
    avg = (mc / hc) if (mc is not None and hc) else None
    return {"turnover": turnover, "avg_holding_usd": avg}


def _gt(v: Optional[float], thr: float) -> Optional[bool]:
    return None if v is None else v > thr


def _lt(v: Optional[float], thr: float) -> Optional[bool]:
    return None if v is None else v < thr


def derive_features(row: dict, thr: dict) -> dict:
    sw = row.get("smart_wallets")
    kol = row.get("kol_wallets")
    honeypot = row.get("is_honeypot")
    osrc = row.get("open_source")
    renounced = row.get("owner_renounced")
    buy_tax = row.get("buy_tax")
    sell_tax = row.get("sell_tax")
    tax = None
    if buy_tax is not None or sell_tax is not None:
        tax = (buy_tax or 0) > 0 or (sell_tax or 0) > 0
    return {
        "smart_money_zero": None if sw is None else sw == 0,
        "kol_zero": None if kol is None else kol == 0,
        "high_bundler": _gt(row.get("bundler_rate"), thr["high_bundler"]),
        "high_fresh": _gt(row.get("fresh_wallet_rate"), thr["high_fresh"]),
        "high_rat": _gt(row.get("rat_rate"), thr["high_rat"]),
        "high_top10": _gt(row.get("top10_rate"), thr["high_top10"]),
        "high_dev": _gt(row.get("dev_hold_rate"), thr["high_dev"]),
        "high_bot": _gt(row.get("bot_degen_rate"), thr["high_bot"]),
        "low_turnover": _lt(row.get("turnover"), thr["low_turnover"]),
        "low_liquidity": _lt(row.get("liquidity"), thr["low_liquidity"]),
        "high_rug": _gt(row.get("rug_ratio"), thr["high_rug"]),
        "high_entrapment": _gt(row.get("entrapment_rate"), thr["high_entrapment"]),
        "low_holders": _lt(row.get("holder_count"), thr["low_holders"]),
        "honeypot": None if honeypot is None else honeypot == "yes",
        "not_open_source": None if osrc is None else osrc == "no",
        "not_renounced": None if renounced is None else renounced == "no",
        "has_tax": tax,
    }
