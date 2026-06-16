from __future__ import annotations

from typing import Optional

from app.gmgn import normalize_chain


def parse_task(task: dict) -> Optional[dict]:
    """把金狗雷达 task 转成入场行的金狗雷达部分；缺 token 返回 None。"""
    token = (task.get("input") or {}).get("token")
    if not token or not token.get("address"):
        return None
    metrics = token.get("metrics") or {}
    score = task.get("latest_score") or {}
    return {
        "task_id": task.get("id"),
        "token_key": task.get("token_key"),
        "address": token.get("address"),
        "chain": normalize_chain(token.get("chain", "")),
        "symbol": token.get("symbol"),
        "name": token.get("name"),
        "pushed_at": task.get("created_at"),
        "grade": score.get("grade"),
        "narrative": task.get("detailed_narrative") or task.get("summary"),
        "price": metrics.get("price"),
        "liquidity": metrics.get("liquidity"),
        "volume_24h": metrics.get("volume_24h"),
        "market_cap": metrics.get("market_cap"),
        "holder_count": metrics.get("holder_count"),
        "top10_position": metrics.get("top10_position"),
        "creation_timestamp": token.get("creation_timestamp"),
    }
