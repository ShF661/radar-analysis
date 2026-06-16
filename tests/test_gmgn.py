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
