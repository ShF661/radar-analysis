from app.config import Settings


def test_chains_parsed_from_env(monkeypatch):
    monkeypatch.setenv("RADAR_CHAINS", "sol, eth ,BSC")
    s = Settings()
    assert s.chains == ["sol", "eth", "bsc"]


def test_base_url_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("RADAR_BASE_URL", "http://x:11800/")
    assert Settings().radar_base_url == "http://x:11800"
