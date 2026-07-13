from app.backtest import normalize_backtest_token


def test_normalize_backtest_token_converts_multiples_to_percentages():
    row = normalize_backtest_token({
        "id": "bt-1",
        "token_address": "addr",
        "token_chain": "solana",
        "base_market_cap": 100.0,
        "peak_market_cap": 250.0,
        "peak_market_multiple": 2.5,
        "settlement_market_cap": 40.0,
        "settlement_market_multiple": 0.4,
        "status": "settled",
    })
    assert row["backtest_id"] == "bt-1"
    assert row["chain"] == "sol"
    assert row["base_market_cap"] == 100.0
    assert row["peak_market_cap"] == 250.0
    assert row["peak_gain_pct"] == 150.0
    assert row["settlement_gain_pct"] == -60.0
    assert row["max_drop_pct"] == 60.0


def test_normalize_backtest_token_prefers_explicit_drop_fields():
    row = normalize_backtest_token({
        "base_market_cap": 100.0,
        "peak_market_multiple": 1.5,
        "settlement_market_multiple": 0.2,
        "max_drop_pct": 35.0,
    })
    assert row["max_drop_pct"] == 35.0

