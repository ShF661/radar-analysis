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
