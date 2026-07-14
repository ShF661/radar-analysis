from __future__ import annotations

from typing import Optional

import httpx

from app.backtest import backtest_date_window, normalize_backtest_token, same_token
from app.gmgn import normalize_chain


def _hit_to_int(v) -> int | None:
    if v == "hit":
        return 1
    if v == "miss":
        return 0
    return None  # "pending" or None → not yet determined


def parse_task(task: dict) -> dict | None:
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
        "narrative_hit": _hit_to_int(score.get("hit_status")),
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

    def _fetch_tasks_by_state(
        self, state: str, page_size: int = 100, max_pages: int = 100
    ) -> list[dict]:
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            r = self._get("/api/v1/tasks", {
                "state": state,
                "page": page,
                "page_size": page_size,
                "sort_by": "created_at",
                "sort_order": "desc",
            })
            body = r.json()
            items = body.get("data", [])
            pagination = body.get("pagination") or {}
            out.extend(items)
            total = pagination.get("total") or body.get("total")
            effective_size = pagination.get("page_size") or page_size
            if not items or len(items) < effective_size:
                break
            if total is not None and len(out) >= total:
                break
        return out

    def fetch_completed_tasks(self, page_size: int = 100, max_pages: int = 1) -> list[dict]:
        return self._fetch_tasks_by_state("completed", page_size, max_pages)

    def fetch_filtered_tasks(self, page_size: int = 100, max_pages: int = 1) -> list[dict]:
        """Fetch tasks pre-filtered by the radar backend (metric_filtered / safety_filtered)."""
        out: list[dict] = []
        for state in ("metric_filtered", "safety_filtered"):
            try:
                out.extend(self._fetch_tasks_by_state(state, page_size, max_pages))
            except Exception as e:
                print(f"[radar] fetch_filtered_tasks state={state} error: {e}", flush=True)
        return out

    def get_task(self, task_id: str) -> Optional[dict]:
        """Fetch a single task by ID. Returns None on 404 or error."""
        try:
            r = self._get(f"/api/v1/tasks/{task_id}", {})
            body = r.json()
            return body.get("data") or body if isinstance(body, dict) else None
        except Exception:
            return None

    def fetch_backtest_tokens(
        self,
        start_date: str,
        end_date: str,
        page_size: int = 100,
        max_pages: int = 100,
        sort_by: str = "first_push_at",
        sort_order: str = "asc",
        search: str | None = None,
    ) -> list[dict]:
        out: list[dict] = []
        page = 1
        total: int | None = None
        while page <= max_pages:
            r = self._get("/api/v1/backtests/tokens", {
                "start_date": start_date,
                "end_date": end_date,
                "page": page,
                "page_size": page_size,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "search": search,
            })
            body = r.json()
            items = body.get("data") or body.get("items") or body.get("tokens") or []
            pagination = body.get("pagination") or {}
            if total is None:
                total = pagination.get("total") or body.get("total")
            out.extend(items)
            eff_page_size = pagination.get("page_size") or page_size
            if not items:
                break
            if total is not None and len(out) >= total:
                break
            if len(items) < eff_page_size:
                break
            page += 1
        return out

    def find_backtest_token(self, address: str, chain: str, pushed_at: str | None = None) -> Optional[dict]:
        start_date, end_date = backtest_date_window(pushed_at)
        for raw in self.fetch_backtest_tokens(
            start_date=start_date,
            end_date=end_date,
            search=address,
            max_pages=5,
        ):
            bt = normalize_backtest_token(raw)
            if same_token(bt, address, chain):
                return bt
        return None

    def close(self) -> None:
        self._http.close()
