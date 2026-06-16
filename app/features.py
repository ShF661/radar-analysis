from __future__ import annotations

# 阈值：把连续数值指标转成“是/否”特征的判定线。前端 /api/defaults 取用。
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

# 特征中文名。前端 /api/defaults 取用。
# 注意：特征派生 / 分桶 / 占比统计的“唯一权威实现”在前端 web/app.js（按链区分），
# 后端不再重复实现，避免两份逻辑漂移。
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
    "security_risk": "有安全风险",
}


def derive_metrics(row: dict) -> dict:
    """派生指标：换手率 = 成交量/市值，人均持币 = 市值/持有人数。"""
    vol = row.get("volume_24h")
    mc = row.get("market_cap")
    hc = row.get("holder_count")
    turnover = (vol / mc) if (vol is not None and mc) else None
    avg = (mc / hc) if (mc is not None and hc) else None
    return {"turnover": turnover, "avg_holding_usd": avg}
