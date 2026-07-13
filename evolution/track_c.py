"""
Track C mode discovery — manual trigger.

  python -m evolution.track_c

Reads 30 days of failure cases, calls failure_pattern_mining, pushes to Feishu.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.config import load_settings
from evolution.db import EvolutionDB
from evolution.feishu import push


def _load_env() -> None:
    from pathlib import Path
    f = Path(".env")
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        import os
        os.environ.setdefault(k.strip(), v.strip())


_MIN_CASES = 30


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    _load_env()
    settings = load_settings()

    if not settings.feishu_webhook:
        print("[track_c] FEISHU_WEBHOOK not set, aborting", flush=True)
        sys.exit(1)
    if not (settings.langfuse_public_key and settings.llm_api_key):
        print("[track_c] LLM not configured, aborting", flush=True)
        sys.exit(1)

    evo_db = EvolutionDB(settings.db_path)
    evo_db.init_schema()
    cases = evo_db.cases_for_prompt_test(days=30)
    evo_db.close()

    failure_cases = [c for c in cases if c.get("narrative_hit") == 0]

    if len(failure_cases) < _MIN_CASES:
        msg = (
            f"📊 Track C — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"样本不足（当前 {len(failure_cases)} 条，需 ≥{_MIN_CASES} 条），暂不分析。"
        )
        push(settings.feishu_webhook, msg)
        print(f"[track_c] insufficient samples ({len(failure_cases)})", flush=True)
        return

    from evolution.llm import LLMClient
    llm = LLMClient.from_settings(settings)

    variables = {
        "date":          datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "failure_count": str(len(failure_cases)),
        "cases":         json.dumps(failure_cases, ensure_ascii=False),
    }

    print(f"[track_c] calling LLM with {len(failure_cases)} failure cases...", flush=True)
    result = llm.call_text(
        "failure_pattern_mining",
        variables,
        settings.llm_model_pro,
    )
    llm.flush()

    header = f"🔍 Track C 模式发现 — {variables['date']}\n\n"
    push(settings.feishu_webhook, header + result)
    print("[track_c] pushed to Feishu", flush=True)


if __name__ == "__main__":
    main()
