import json
from pathlib import Path

from app.radar import parse_task

FX = Path(__file__).parent / "fixtures"


def test_parse_task_extracts_identity_and_metrics():
    task = json.loads((FX / "task.json").read_text(encoding="utf-8"))
    row = parse_task(task)
    assert row["task_id"] == "task-123"
    assert row["address"] == "TKN"
    assert row["chain"] == "sol"           # normalized
    assert row["symbol"] == "TKN"
    assert row["pushed_at"] == "2026-06-16T08:00:00Z"
    assert row["grade"] == "B"
    assert row["narrative"] == "long narrative text"
    assert row["volume_24h"] == 120000
    assert row["holder_count"] == 320
    assert row["market_cap"] == 500000
    assert row["creation_timestamp"] == 1718500000


def test_parse_task_missing_token_returns_none():
    assert parse_task({"id": "x", "input": {}}) is None


import httpx
from app.radar import RadarClient


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_client_logs_in_and_sets_bearer():
    calls = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT"})
        calls["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [], "pagination": {"page": 1, "page_size": 50, "total": 0}})

    client = RadarClient("http://x", "u", "p", transport=_mock_transport(handler))
    client.login()
    client.fetch_completed_tasks(page_size=50)
    assert calls["auth"] == "Bearer AT"


def test_fetch_completed_tasks_returns_data_list():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT"})
        return httpx.Response(200, json={"data": [{"id": "t1"}, {"id": "t2"}], "pagination": {"page": 1, "page_size": 50, "total": 2}})

    client = RadarClient("http://x", "u", "p", transport=_mock_transport(handler))
    client.login()
    tasks = client.fetch_completed_tasks()
    assert [t["id"] for t in tasks] == ["t1", "t2"]


def test_fetch_completed_tasks_reads_all_pages():
    requested_pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT"})
        page = int(request.url.params["page"])
        requested_pages.append(page)
        data = [{"id": f"t{page}"}] if page <= 3 else []
        return httpx.Response(200, json={
            "data": data,
            "pagination": {"page": page, "page_size": 1, "total": 3},
        })

    client = RadarClient("http://x", "u", "p", transport=_mock_transport(handler))
    client.login()
    tasks = client.fetch_completed_tasks(page_size=1, max_pages=100)

    assert [t["id"] for t in tasks] == ["t1", "t2", "t3"]
    assert requested_pages == [1, 2, 3]


def test_fetch_filtered_tasks_rejects_wrong_states_from_backend():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT"})
        requested_state = request.url.params["state"]
        return httpx.Response(200, json={
            "data": [
                {"id": f"{requested_state}-ok", "state": requested_state},
                {"id": "wrong", "state": "completed"},
            ],
            "pagination": {"page": 1, "page_size": 100, "total": 2},
        })

    client = RadarClient("http://x", "u", "p", transport=_mock_transport(handler))
    client.login()

    tasks = client.fetch_filtered_tasks()
    assert [task["id"] for task in tasks] == [
        "metric_filtered-ok",
        "safety_filtered-ok",
    ]


def test_request_retries_once_after_401_refresh():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT"})
        if p == "/api/v1/auth/refresh":
            return httpx.Response(200, json={"access_token": "AT2", "refresh_token": "RT2"})
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"data": [], "pagination": {"page": 1, "page_size": 50, "total": 0}})

    client = RadarClient("http://x", "u", "p", transport=_mock_transport(handler))
    client.login()
    client.fetch_completed_tasks()
    assert state["n"] == 2
