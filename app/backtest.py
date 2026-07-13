from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.gmgn import normalize_chain

CN_TZ = timezone(timedelta(hours=8))


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct_from_multiple(multiple: Optional[float]) -> Optional[float]:
    if multiple is None:
        return None
    return round((multiple - 1.0) * 100.0, 10)


def _drop_from_multiple(multiple: Optional[float]) -> Optional[float]:
    if multiple is None:
        return None
    return round(max(0.0, (1.0 - multiple) * 100.0), 10)


def parse_time(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def backtest_date_window(pushed_at: str | None, days_after: int = 1) -> tuple[str, str]:
    pushed = parse_time(pushed_at)
    if pushed is None:
        local = datetime.now(CN_TZ)
    else:
        local = pushed.astimezone(CN_TZ)
    start = (local.date() - timedelta(days=1)).isoformat()
    end = (datetime.now(CN_TZ).date() + timedelta(days=days_after)).isoformat()
    if end < start:
        end = start
    return start, end


def normalize_backtest_token(item: dict) -> dict:
    token = item.get("token") if isinstance(item.get("token"), dict) else item
    base_mc = _f(token.get("base_market_cap"))
    peak_mc = _f(token.get("peak_market_cap"))
    peak_multiple = _f(token.get("peak_market_multiple")) or _f(token.get("peak_multiple"))
    if peak_multiple is None and base_mc and peak_mc is not None:
        peak_multiple = peak_mc / base_mc
    if peak_mc is None and base_mc is not None and peak_multiple is not None:
        peak_mc = base_mc * peak_multiple

    settlement_mc = _f(token.get("settlement_market_cap"))
    settlement_multiple = (
        _f(token.get("settlement_market_multiple"))
        or _f(token.get("settlement_multiple"))
    )
    if settlement_multiple is None and base_mc and settlement_mc is not None:
        settlement_multiple = settlement_mc / base_mc
    if settlement_mc is None and base_mc is not None and settlement_multiple is not None:
        settlement_mc = base_mc * settlement_multiple

    min_mc = (
        _f(token.get("min_market_cap"))
        or _f(token.get("lowest_market_cap"))
        or _f(token.get("low_market_cap"))
    )
    min_multiple = (
        _f(token.get("min_market_multiple"))
        or _f(token.get("lowest_market_multiple"))
        or _f(token.get("low_market_multiple"))
    )
    if min_multiple is None and base_mc and min_mc is not None:
        min_multiple = min_mc / base_mc
    if min_mc is None and base_mc is not None and min_multiple is not None:
        min_mc = base_mc * min_multiple

    max_drop = (
        _f(token.get("max_drop_pct"))
        or _f(token.get("max_drawdown_pct"))
        or _f(token.get("drawdown_pct"))
    )
    if max_drop is None:
        low_gain = _f(token.get("lowest_gain_pct")) or _f(token.get("min_gain_pct"))
        if low_gain is not None:
            max_drop = max(0.0, -low_gain)
    if max_drop is None:
        max_drop = _drop_from_multiple(min_multiple)
    # The backtest token list currently exposes settlement, not an intrawindow low.
    # Use it only as a backtest-derived fallback so the field no longer drifts
    # with the old GMGN polling logic.
    if max_drop is None:
        max_drop = _drop_from_multiple(settlement_multiple)

    return {
        "backtest_id": token.get("id"),
        "address": token.get("token_address") or token.get("address"),
        "chain": normalize_chain(token.get("token_chain") or token.get("chain") or ""),
        "token_key": token.get("token_key"),
        "symbol": token.get("token_symbol") or token.get("symbol"),
        "name": token.get("token_name") or token.get("name"),
        "first_push_at": token.get("first_push_at"),
        "base_market_cap": base_mc,
        "peak_market_cap": peak_mc,
        "peak_market_multiple": peak_multiple,
        "peak_gain_pct": _pct_from_multiple(peak_multiple),
        "settlement_market_cap": settlement_mc,
        "settlement_market_multiple": settlement_multiple,
        "settlement_gain_pct": _pct_from_multiple(settlement_multiple),
        "min_market_cap": min_mc,
        "max_drop_pct": max_drop,
        "status": token.get("status"),
        "last_market_at": token.get("last_market_at"),
    }


def same_token(backtest: dict, address: str, chain: str | None = None) -> bool:
    if (backtest.get("address") or "").lower() != (address or "").lower():
        return False
    if chain:
        return backtest.get("chain") == normalize_chain(chain)
    return True

