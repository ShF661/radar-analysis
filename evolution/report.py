"""Build Feishu report text from stats and optional AI summary."""
from __future__ import annotations

import json
from collections import Counter
from typing import Optional, Sequence


def _format_security_risk_list(security_cases: list[dict]) -> str:
    """Format security-risk cases as bullet list for the prompt variable."""
    lines = []
    for c in security_cases:
        symbol = c.get("symbol") or "?"
        chain  = c.get("chain") or "?"
        detail = c.get("security_risk_detail") or ""
        if not detail:
            # Reconstruct from raw fields when detail string is absent
            parts = []
            if c.get("is_honeypot"):
                parts.append("蜜罐合约")
            if c.get("rug_ratio") is not None and float(c["rug_ratio"]) > 0.3:
                parts.append(f"rug率 {c['rug_ratio']:.0%}")
            if c.get("buy_tax") is not None and float(c["buy_tax"]) > 10:
                parts.append(f"买入税 {c['buy_tax']:.0f}%")
            if c.get("sell_tax") is not None and float(c["sell_tax"]) > 10:
                parts.append(f"卖出税 {c['sell_tax']:.0f}%")
            detail = "、".join(parts) if parts else "安全异常"
        lines.append(f"• {symbol} ({chain}) — {detail}")
    return "\n".join(lines) if lines else "（无）"


def build_filtered_section(filtered_cases: Sequence[dict]) -> str:
    """Format today's radar-pre-filtered tokens for the daily Feishu report.

    Shows input metrics + matched filter rules so retrospective review is
    possible without needing gain/performance data (which filtered tokens lack).
    """
    if not filtered_cases:
        return ""

    metric_cases = [c for c in filtered_cases if (c.get("filter_type") or "") in ("metric", "metric_filtered")]
    safety_cases = [c for c in filtered_cases if (c.get("filter_type") or "") in ("safety", "safety_filtered")]

    lines: list[str] = [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🚫 今日过滤代币 — {len(filtered_cases)} 个（指标 {len(metric_cases)} | 安全 {len(safety_cases)}）",
    ]

    # Top rules across all filtered tokens
    rule_counter: Counter[str] = Counter()
    for c in filtered_cases:
        for rule in (c.get("matched_rules") or []):
            rule_counter[str(rule).strip()] += 1
    if rule_counter:
        top = "、".join(f"{rule}({cnt}次)" for rule, cnt in rule_counter.most_common(3))
        lines.append(f"Top命中规则：{top}")

    def _fmt(c: dict) -> str:
        symbol = c.get("symbol") or "?"
        chain = (c.get("chain") or "?").upper()
        rules = "、".join(str(r) for r in (c.get("matched_rules") or []))
        parts: list[str] = [f"• {symbol} ({chain})"]
        hc = c.get("holder_count")
        if hc is not None:
            parts.append(f"持有人{int(hc)}")
        liq = c.get("liquidity")
        if liq is not None:
            liq = float(liq)
            parts.append(f"流动性${liq/1000:.1f}K" if liq >= 1000 else f"流动性${liq:.0f}")
        top10 = c.get("top10_rate")
        if top10 is not None:
            parts.append(f"Top10:{float(top10)*100:.0f}%")
        bundler = c.get("bundler_rate")
        if bundler is not None:
            parts.append(f"打包:{float(bundler)*100:.0f}%")
        line = "  ".join(parts)
        if rules:
            line += f" → {rules}"
        return line

    SHOW_LIMIT = 20

    if metric_cases:
        lines.append("")
        lines.append("📊 指标过滤：")
        for c in metric_cases[:SHOW_LIMIT]:
            lines.append(_fmt(c))
        if len(metric_cases) > SHOW_LIMIT:
            lines.append(f"  …（另 {len(metric_cases) - SHOW_LIMIT} 个，未显示）")

    if safety_cases:
        lines.append("")
        lines.append("🛡 安全过滤：")
        for c in safety_cases[:SHOW_LIMIT]:
            lines.append(_fmt(c))
        if len(safety_cases) > SHOW_LIMIT:
            lines.append(f"  …（另 {len(safety_cases) - SHOW_LIMIT} 个，未显示）")

    return "\n".join(lines)


def build_daily_report(
    date_str: str,
    stats: dict,
    ai_summary: Optional[str] = None,
    filtered_cases: Sequence[dict] | None = None,
) -> str:
    total          = stats.get("total") or 0
    gain_100       = stats.get("gain_100") or 0
    high_gain      = stats.get("high_gain") or 0
    flash_crash    = stats.get("flash_crash") or 0
    grade_mismatch = stats.get("grade_mismatch") or 0
    security_risk  = stats.get("security_risk") or 0
    trusted_total  = stats.get("trusted_total") or 0
    gain_sample_all = stats.get("gain_sample_all") or 0

    win_rate_value = stats.get("win_rate")
    if win_rate_value is None:
        win_rate_value = gain_100 / gain_sample_all if gain_sample_all else 0
    high_gain_rate_value = stats.get("high_gain_rate")
    if high_gain_rate_value is None:
        high_gain_rate_value = high_gain / gain_sample_all if gain_sample_all else 0

    win_rate      = f"{win_rate_value * 100:.1f}%" if gain_sample_all else "—"
    high_gain_rate = f"{high_gain_rate_value * 100:.1f}%" if gain_sample_all else "—"

    lines = [
        f"📊 金狗雷达日报 — {date_str}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "📈 今日推送概览",
        f"• 今日推荐代币数量（全量）：{total} 个",
        f"• 回测样本：{gain_sample_all} 个（可信信号 {trusted_total} 个）",
        f"• 推荐后涨幅 ≥100%：{gain_100} 个 → 胜率 {win_rate}",
        f"• 推荐后涨幅 ≥50%：{high_gain} 个 → 占比 {high_gain_rate}",
        f"• 推荐后闪崩（可信样本）：{flash_crash} 个",
        f"• 叙事评级未命中（满24h）：{grade_mismatch} 个",
        f"• 安全风险代币（可信样本）：{security_risk} 个",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]

    if ai_summary:
        lines.append(ai_summary.strip())

    if filtered_cases is not None:
        section = build_filtered_section(filtered_cases)
        if section:
            lines.append("")
            lines.append(section)

    return "\n".join(lines)


def build_no_data_notice(date_str: str) -> str:
    return f"📊 金狗雷达日报 — {date_str}\n\n今日无已完成分析的代币数据。"


def _loads_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _cases_with_tag(cases: list[dict], tag: str) -> list[dict]:
    return [case for case in cases if tag in _loads_list(case.get("tags"))]


def _top_chains(cases: list[dict], limit: int = 2) -> str:
    counts = Counter(str(case.get("chain") or "unknown") for case in cases)
    return "、".join(f"{chain} {count} 个" for chain, count in counts.most_common(limit)) or "链分布不明"


def _top_filter_signals(cases: list[dict], limit: int = 3) -> list[str]:
    signals: Counter[str] = Counter()
    for case in cases:
        signals.update(str(s).strip() for s in _loads_list(case.get("filter_signals")) if s)
    return [signal for signal, _ in signals.most_common(limit)]


def _top_prompt_issues(cases: list[dict], limit: int = 2) -> list[str]:
    issues: Counter[str] = Counter()
    for case in cases:
        issue = str(case.get("prompt_issue") or "").strip()
        if issue:
            issues[issue] += 1
    return [issue for issue, _ in issues.most_common(limit)]


def _summarize_case_group(cases: list[dict], label: str) -> tuple[str, str]:
    chains = _top_chains(cases)
    signals = _top_filter_signals(cases)
    signal_text = "；".join(signals[:2]) if signals else "过滤信号分散，需继续积累样本"

    if label == "flash_crash":
        summary = (
            f"闪崩案例主要集中在 {chains}。"
            f"共同特征是早期热度衰退快、社区或持币基础弱，典型信号包括：{signal_text}。"
        )
        direction = "推送前增加闪崩前置信号拦截，重点过滤低持有人、低流动性、叙事来源不明且短时回撤过深的标的。"
    elif label == "low_gain":
        summary = (
            f"低涨幅案例主要集中在 {chains}。"
            f"共同问题是叙事传播不足、聪明钱/KOL 参与偏弱或流动性承接不足，典型信号包括：{signal_text}。"
        )
        direction = "提高叙事来源、社区参与、聪明钱数量和流动性阈值，对纯梗文化或单点 KOL 驱动标的降权。"
    else:
        summary = (
            f"该类案例主要集中在 {chains}。"
            f"共同特征包括：{signal_text}。"
        )
        direction = "对高频共同信号设置硬过滤或降权规则，并持续回测阈值。"

    return summary, direction


def build_local_summary(
    stats: dict,
    failure_cases: list[dict],
    security_cases: list[dict],
) -> str:
    """Build fallback summary in the same shape as daily_improvement_report."""
    flash_count = stats.get("flash_crash") or 0
    low_gain_count = stats.get("low_gain") or 0
    grade_mismatch_count = stats.get("grade_mismatch") or 0
    security_risk_count = stats.get("security_risk") or 0

    flash_cases = _cases_with_tag(failure_cases, "flash_crash")
    low_gain_cases = _cases_with_tag(failure_cases, "low_gain")
    grade_mismatch_cases = _cases_with_tag(failure_cases, "grade_mismatch")

    lines = [
        "🔍 问题案例总结 & 优化建议",
        "",
        f"📉 闪崩（{flash_count} 个）",
    ]

    if flash_count == 0 or not flash_cases:
        lines.append("今日无此类案例")
    else:
        summary, direction = _summarize_case_group(flash_cases, "flash_crash")
        lines.extend([summary, f"→ 过滤方向：{direction}"])

    lines.extend(["", f"📊 涨幅低于 50%（{low_gain_count} 个）"])
    if low_gain_count == 0 or not low_gain_cases:
        lines.append("今日无此类案例")
    else:
        summary, direction = _summarize_case_group(low_gain_cases, "low_gain")
        lines.extend([summary, f"→ 过滤方向：{direction}"])

    lines.extend(["", f"🎯 叙事评级未命中（{grade_mismatch_count} 个）"])
    if grade_mismatch_count == 0 or not grade_mismatch_cases:
        lines.append("今日无此类案例")
    else:
        issues = _top_prompt_issues(grade_mismatch_cases)
        issue_text = "；".join(issues) if issues else "S/A 级叙事对真实传播与链上承接的校验不足"
        summary = (
            f"未命中案例主要集中在 {_top_chains(grade_mismatch_cases)}。"
            f"偏差集中在过度相信叙事热度或 KOL 背书，未充分惩罚传播停滞、流动性弱和社区基础薄弱；典型偏差：{issue_text}。"
        )
        direction = "在 S/A 评级提示词中加入反证检查：叙事源是否持续、KOL/聪明钱是否真实扩散、流动性和持有人是否足以支撑评级。"
        lines.extend([summary, f"→ 提示词优化方向：{direction}"])

    lines.extend(["", f"🛡 安全风险（{security_risk_count} 个）"])
    if security_risk_count == 0 or not security_cases:
        lines.append("今日无此类案例")
    else:
        lines.append(_format_security_risk_list(security_cases))
        risk_summary = (
            f"安全风险案例主要集中在 {_top_chains(security_cases)}。"
            "风险类型以合约/税率/rug 相关异常为主，需要在推荐前置阶段直接拦截。"
        )
        lines.extend([
            risk_summary,
            "→ 过滤方向：对蜜罐、高税率、rug 比例异常和安全详情非空的代币执行硬过滤，不进入叙事评级环节。",
        ])

    lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━"])
    return "\n".join(lines)


def build_ai_summary_vars(
    date_str: str,
    stats: dict,
    failure_cases: list[dict],
    security_cases: list[dict],
) -> dict:
    """Prepare variables dict for daily_improvement_report Langfuse prompt."""
    def _by_tag(tag: str) -> list[dict]:
        return [c for c in failure_cases if tag in _loads_list(c.get("tags"))]

    flash_cases        = _by_tag("flash_crash")
    low_gain_cases     = _by_tag("low_gain")
    grade_mismatch_cases = _by_tag("grade_mismatch")

    total    = stats.get("total") or 0
    gain_100 = stats.get("gain_100") or 0
    gain_sample_total = stats.get("gain_sample_total") or 0

    return {
        "date":                    date_str,
        "total":                   str(total),
        "win_rate":                f"{gain_100 / gain_sample_total * 100:.1f}%" if gain_sample_total else "0%",
        "flash_crash_count":       str(stats.get("flash_crash") or 0),
        "flash_crash_cases":       json.dumps(flash_cases, ensure_ascii=False),
        "low_gain_count":          str(stats.get("low_gain") or 0),
        "low_gain_cases":          json.dumps(low_gain_cases, ensure_ascii=False),
        "grade_mismatch_count":    str(stats.get("grade_mismatch") or 0),
        "grade_mismatch_cases":    json.dumps(grade_mismatch_cases, ensure_ascii=False),
        "security_risk_count":     str(stats.get("security_risk") or 0),
        "security_risk_list":      _format_security_risk_list(security_cases),
    }
