"""
Prompt batch test — manual trigger.

  python -m evolution.prompt_test

Re-runs evolution_prompt_test against past 30 days of cases,
computes two metrics, pushes a structured report to Feishu.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Optional

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
_HIGH_GRADES = {"S", "A"}


def _run_test(llm, cases: list[dict], model: str) -> list[dict]:
    """Re-run prompt for each case, return list of result dicts."""
    results = []
    for c in cases:
        try:
            raw = llm.call_json(
                "prompt_batch_test",
                {"prompt_input_snapshot": c["prompt_input_snapshot"]},
                model,
                trace_id=c["push_record_id"],
            )
            new_grade = str(raw.get("grade") or raw.get("narrative_grade") or "")
            results.append({
                "push_record_id":   c["push_record_id"],
                "original_grade":   c.get("narrative_grade") or "",
                "new_grade":        new_grade,
                "narrative_hit":    c.get("narrative_hit"),
            })
        except Exception as e:
            print(f"[prompt_test] skipped {c['push_record_id'][:8]}: {e}", flush=True)
    return results


def _compute_metrics(results: list[dict]) -> dict:
    fail_group  = [r for r in results if r["narrative_hit"] == 0]
    succ_group  = [r for r in results if r["narrative_hit"] == 1]

    orig_fail_high = sum(1 for r in fail_group if r["original_grade"] in _HIGH_GRADES)
    new_fail_high  = sum(1 for r in fail_group if r["new_grade"] in _HIGH_GRADES)
    orig_succ_high = sum(1 for r in succ_group if r["original_grade"] in _HIGH_GRADES)
    new_succ_high  = sum(1 for r in succ_group if r["new_grade"] in _HIGH_GRADES)

    reduction: Optional[float] = None
    if orig_fail_high > 0:
        reduction = (orig_fail_high - new_fail_high) / orig_fail_high * 100

    retention: Optional[float] = None
    if orig_succ_high > 0:
        retention = new_succ_high / orig_succ_high * 100

    return {
        "fail_group_count": len(fail_group),
        "succ_group_count": len(succ_group),
        "old_mismatch":     orig_fail_high,
        "new_mismatch":     new_fail_high,
        "improvement_pct":  round(reduction, 2) if reduction is not None else None,
        "retention_pct":    round(retention, 2) if retention is not None else None,
    }


def _conclusion(m: dict) -> tuple[str, str]:
    imp  = m.get("improvement_pct")
    ret  = m.get("retention_pct")
    orig = m.get("old_mismatch", 0)

    if orig == 0:
        return "无优化空间", "原提示词对此批数据已无误判，无优化空间，不产出结论"
    if imp is None:
        return "数据不足", "叙事失败组无有效样本，无法计算误判减少率"
    if imp >= 20 and (ret is None or ret >= 80):
        return "建议采用", f"误判减少 {imp:.1f}%，高评留存 {ret:.1f}%，两项指标均达标"
    if imp >= 20 and ret is not None and ret < 80:
        return "谨慎", f"误判减少 {imp:.1f}% 达标，但高评留存仅 {ret:.1f}%，好代币损失过多"
    if imp < 0:
        return "不采用", f"误判数量反而增加 {abs(imp):.1f}%"
    return "不建议采用", f"误判改善 {imp:.1f}%，未达 20% 阈值"


def _build_feishu_msg(date_str: str, token_count: int, m: dict, conclusion: str, reason: str) -> str:
    imp_str = f"{m['improvement_pct']:.1f}%" if m.get("improvement_pct") is not None else "—"
    ret_str = f"{m['retention_pct']:.1f}%" if m.get("retention_pct") is not None else "—"
    return (
        f"📊 提示词批量测试报告 — {date_str}\n\n"
        f"测试数据：过去30天 {token_count} 个代币\n"
        f"叙事失败组：{m['fail_group_count']} 个 | 叙事成功组：{m['succ_group_count']} 个\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"① 误判减少（叙事未命中但被高评）\n"
        f"   原提示词：{m['old_mismatch']} 个误判\n"
        f"   新提示词：{m['new_mismatch']} 个误判\n"
        f"   改善：{imp_str}\n\n"
        f"② 正确高评留存（叙事命中且高评）\n"
        f"   留存率：{ret_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"结论：{conclusion}\n"
        f"原因：{reason}\n\n"
        f"⚠️ 最终决定由人工确认后更新 Langfuse"
    )


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    _load_env()
    settings = load_settings()

    if not settings.feishu_webhook:
        print("[prompt_test] FEISHU_WEBHOOK not set, aborting", flush=True)
        sys.exit(1)
    if not (settings.langfuse_public_key and settings.llm_api_key):
        print("[prompt_test] LLM not configured, aborting", flush=True)
        sys.exit(1)

    evo_db = EvolutionDB(settings.db_path)
    evo_db.init_schema()
    cases = evo_db.cases_for_prompt_test(days=30)
    evo_db.close()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if len(cases) < _MIN_CASES:
        msg = (
            f"📊 提示词批量测试报告 — {date_str}\n\n"
            f"样本不足（当前 {len(cases)} 条，需 ≥{_MIN_CASES} 条），不产出结论。"
        )
        push(settings.feishu_webhook, msg)
        print(f"[prompt_test] insufficient samples ({len(cases)})", flush=True)
        return

    from evolution.llm import LLMClient
    llm = LLMClient.from_settings(settings)

    print(f"[prompt_test] running on {len(cases)} cases...", flush=True)
    results = _run_test(llm, cases, settings.llm_model_fast)
    llm.flush()

    valid = [r for r in results if r["narrative_hit"] is not None]
    if len(valid) < _MIN_CASES:
        msg = (
            f"📊 提示词批量测试报告 — {date_str}\n\n"
            f"有效样本不足（{len(valid)} 条），不产出结论。"
        )
        push(settings.feishu_webhook, msg)
        return

    m = _compute_metrics(valid)
    conclusion, reason = _conclusion(m)
    msg = _build_feishu_msg(date_str, len(valid), m, conclusion, reason)

    # Write result to DB
    evo_db2 = EvolutionDB(settings.db_path)
    evo_db2.insert_prompt_test_result({
        "tested_at":        date_str,
        "token_count":      len(valid),
        "fail_group_count": m["fail_group_count"],
        "succ_group_count": m["succ_group_count"],
        "old_mismatch":     m["old_mismatch"],
        "new_mismatch":     m["new_mismatch"],
        "improvement_pct":  m.get("improvement_pct"),
        "retention_pct":    m.get("retention_pct"),
        "conclusion":       conclusion,
        "applied":          0,
        "note":             reason,
    })
    evo_db2.close()

    print(msg, flush=True)
    push(settings.feishu_webhook, msg)
    print("[prompt_test] pushed to Feishu", flush=True)


if __name__ == "__main__":
    main()
