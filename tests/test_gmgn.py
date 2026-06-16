import json
from pathlib import Path

from app.gmgn import parse_token_info, parse_token_security, unwrap

FX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_unwrap_handles_data_envelope():
    assert unwrap({"data": {"a": 1}}) == {"a": 1}
    assert unwrap({"a": 1}) == {"a": 1}


def test_parse_token_info_core_and_derived():
    info = parse_token_info(_load("token_info.json"))
    assert info["price"] == 0.0005
    assert info["holder_count"] == 320
    assert info["volume_24h"] == 120000
    assert info["market_cap"] == 500000
    assert info["top10_rate"] == 0.42
    assert info["dev_hold_rate"] == 0.06
    assert info["rat_rate"] == 0.12
    assert info["entrapment_rate"] == 0.08
    assert info["bundler_rate"] == 0.35
    assert info["fresh_wallet_rate"] == 0.55
    assert info["bot_degen_rate"] == 0.4
    assert info["smart_wallets"] == 0
    assert info["kol_wallets"] == 0
    assert info["creation_timestamp"] == 1718500000


def test_parse_token_security_fields():
    sec = parse_token_security(_load("token_security.json"))
    assert sec["is_honeypot"] == "no"
    assert sec["open_source"] == "yes"
    assert sec["owner_renounced"] == "no"
    assert sec["buy_tax"] == 0.03
    assert sec["sell_tax"] == 0.03
    assert sec["rug_ratio"] == 0.12
    assert sec["burn_status"] == ""


def test_parse_token_info_missing_fields_safe():
    info = parse_token_info({"price": {}})
    assert info["price"] is None
    assert info["market_cap"] is None
    assert info["smart_wallets"] is None


from app import gmgn as gmgn_mod


def test_normalize_chain():
    assert gmgn_mod.normalize_chain("solana") == "sol"
    assert gmgn_mod.normalize_chain("ethereum") == "eth"
    assert gmgn_mod.normalize_chain("BSC") == "bsc"
    assert gmgn_mod.normalize_chain("base") == "base"
    assert gmgn_mod.normalize_chain("sol") == "sol"


def test_fetch_snapshot_merges_info_and_security(monkeypatch):
    info = _load("token_info.json")
    sec = _load("token_security.json")

    def fake_run(cli, sub, chain, address):
        return info if sub == "info" else sec

    monkeypatch.setattr(gmgn_mod, "run_gmgn", fake_run)
    snap = gmgn_mod.fetch_snapshot("gmgn-cli", "sol", "TKN")
    assert snap["gmgn_ok"] is True
    assert snap["market_cap"] == 500000
    assert snap["rug_ratio"] == 0.12
    assert snap["is_honeypot"] == "no"


def test_fetch_snapshot_failure_sets_flag(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("cli failed")

    monkeypatch.setattr(gmgn_mod, "run_gmgn", boom)
    snap = gmgn_mod.fetch_snapshot("gmgn-cli", "sol", "TKN")
    assert snap["gmgn_ok"] is False
