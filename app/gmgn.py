from __future__ import annotations

import json
import subprocess
from typing import Any, Optional


def unwrap(obj: Any) -> Any:
    """gmgn-cli --raw 可能直接给对象，也可能包一层 {code,data}。统一取内层。"""
    if isinstance(obj, dict) and "data" in obj and isinstance(obj["data"], (dict, list)):
        return obj["data"]
    return obj


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> Optional[int]:
    f = _f(v)
    return int(f) if f is not None else None


def parse_token_info(raw: Any) -> dict:
    d = unwrap(raw)
    price_obj = d.get("price") or {}
    price = _f(price_obj.get("price"))
    supply = _f(d.get("circulating_supply")) or _f(d.get("total_supply"))
    market_cap = price * supply if (price is not None and supply) else None
    stat = d.get("stat") or {}
    tags = d.get("wallet_tags_stat") or {}
    return {
        "price": price,
        "liquidity": _f(d.get("liquidity")),
        "market_cap": market_cap,
        "volume_24h": _f(price_obj.get("volume_24h")),
        "holder_count": _i(d.get("holder_count") or stat.get("holder_count")),
        "top10_rate": _f(stat.get("top_10_holder_rate")),
        "dev_hold_rate": _f(stat.get("dev_team_hold_rate")),
        "rat_rate": _f(stat.get("top_rat_trader_percentage")),
        "entrapment_rate": _f(stat.get("top_entrapment_trader_percentage")),
        "bundler_rate": _f(stat.get("top_bundler_trader_percentage")),
        "fresh_wallet_rate": _f(stat.get("fresh_wallet_rate")),
        "bot_degen_rate": _f(stat.get("bot_degen_rate")),
        "smart_wallets": _i(tags.get("smart_wallets")),
        "kol_wallets": _i(tags.get("renowned_wallets")),
        "creation_timestamp": _i(d.get("creation_timestamp")),
    }


def parse_token_security(raw: Any) -> dict:
    d = unwrap(raw)
    return {
        "is_honeypot": d.get("is_honeypot") or None,
        "open_source": d.get("open_source") or None,
        "owner_renounced": d.get("owner_renounced") or None,
        "buy_tax": _f(d.get("buy_tax")),
        "sell_tax": _f(d.get("sell_tax")),
        "rug_ratio": _f(d.get("rug_ratio")),
        "burn_status": d.get("burn_status", None),
    }


_CHAIN_MAP = {
    "solana": "sol", "sol": "sol",
    "ethereum": "eth", "eth": "eth",
    "bsc": "bsc", "bnb": "bsc",
    "base": "base",
}


def normalize_chain(chain: str) -> str:
    return _CHAIN_MAP.get((chain or "").lower(), (chain or "").lower())


def run_gmgn(cli: str, sub: str, chain: str, address: str) -> Any:
    """调用 `gmgn-cli token <sub> --chain <chain> --address <addr> --raw`，返回解析后的 JSON。"""
    proc = subprocess.run(
        [cli, "token", sub, "--chain", chain, "--address", address, "--raw"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gmgn-cli {sub} failed: {proc.stderr.strip()[:200]}")
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError(f"gmgn-cli {sub} empty output")
    return json.loads(out)


def fetch_snapshot(cli: str, chain: str, address: str) -> dict:
    """抓 info+security 合成入场快照；失败时 gmgn_ok=False 并保留已得字段。"""
    snap: dict = {"gmgn_ok": False}
    try:
        info_raw = run_gmgn(cli, "info", chain, address)
        snap.update(parse_token_info(info_raw))
        sec_raw = run_gmgn(cli, "security", chain, address)
        snap.update(parse_token_security(sec_raw))
        snap["gmgn_ok"] = True
    except Exception:
        return snap
    return snap


def fetch_market_cap(cli: str, chain: str, address: str) -> Optional[float]:
    """价格刷新用：只取当前市值。失败返回 None。"""
    try:
        info = parse_token_info(run_gmgn(cli, "info", chain, address))
        return info["market_cap"]
    except Exception:
        return None
