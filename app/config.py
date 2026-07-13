from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_chains(raw: str) -> list[str]:
    return [c.strip().lower() for c in raw.split(",") if c.strip()]


@dataclass
class Settings:
    radar_base_url: str = field(default_factory=lambda: os.getenv("RADAR_BASE_URL", "http://127.0.0.1:11800").rstrip("/"))
    radar_username: str = field(default_factory=lambda: os.getenv("RADAR_USERNAME", ""))
    radar_password: str = field(default_factory=lambda: os.getenv("RADAR_PASSWORD", ""))
    chains: list[str] = field(default_factory=lambda: _split_chains(os.getenv("RADAR_CHAINS", "sol,eth,bsc")))
    discover_interval: int = field(default_factory=lambda: int(os.getenv("DISCOVER_INTERVAL", "5")))
    price_interval: int = field(default_factory=lambda: int(os.getenv("PRICE_INTERVAL", "60")))
    track_hours: int = field(default_factory=lambda: int(os.getenv("TRACK_HOURS", "24")))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "./radar.db"))
    gmgn_cli: str = field(default_factory=lambda: os.getenv("GMGN_CLI", "gmgn-cli"))
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8000")))
    gmgn_delay: float = field(default_factory=lambda: float(os.getenv("GMGN_DELAY", "0.8")))
    feishu_webhook: str = field(default_factory=lambda: os.getenv("FEISHU_WEBHOOK", ""))
    langfuse_secret_key: str = field(default_factory=lambda: os.getenv("LANGFUSE_SECRET_KEY", ""))
    langfuse_public_key: str = field(default_factory=lambda: os.getenv("LANGFUSE_PUBLIC_KEY", ""))
    langfuse_host: str = field(default_factory=lambda: os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    llm_model_fast: str = field(default_factory=lambda: os.getenv("LLM_MODEL_FAST", "gpt-4o-mini"))
    llm_model_pro: str = field(default_factory=lambda: os.getenv("LLM_MODEL_PRO", "gpt-4o"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))


def load_settings() -> Settings:
    return Settings()
