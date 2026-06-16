from __future__ import annotations

from typing import Optional

import httpx

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


class RadarClient:
    """金狗雷达后端最小客户端：密码登录 + 拉已完成任务，401 自动 refresh 重试一次。"""

    def __init__(self, base_url: str, username: str, password: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._access: str | None = None
        self._refresh: str | None = None
        self._http = httpx.Client(base_url=self.base_url, transport=transport, timeout=20.0)

    def login(self) -> None:
        r = self._http.post("/api/v1/auth/login", json={"username": self.username, "password": self.password})
        r.raise_for_status()
        data = r.json()
        self._access = data["access_token"]
        self._refresh = data.get("refresh_token")

    def _refresh_token(self) -> bool:
        if not self._refresh:
            return False
        r = self._http.post("/api/v1/auth/refresh", json={"refresh_token": self._refresh})
        if r.status_code != 200:
            return False
        data = r.json()
        self._access = data["access_token"]
        self._refresh = data.get("refresh_token", self._refresh)
        return True

    def _get(self, path: str, params: dict) -> httpx.Response:
        headers = {"authorization": f"Bearer {self._access}"}
        r = self._http.get(path, params=params, headers=headers)
        if r.status_code == 401 and self._refresh_token():
            headers = {"authorization": f"Bearer {self._access}"}
            r = self._http.get(path, params=params, headers=headers)
        r.raise_for_status()
        return r

    def fetch_completed_tasks(self, page_size: int = 100) -> list[dict]:
        r = self._get("/api/v1/tasks", {
            "state": "completed",
            "page": 1,
            "page_size": page_size,
            "sort_by": "created_at",
            "sort_order": "desc",
        })
        return r.json().get("data", [])

    def close(self) -> None:
        self._http.close()
