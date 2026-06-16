from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable

from app.config import Settings
from app.db import Database
from app.features import DEFAULT_THRESHOLDS, derive_features, derive_metrics  # noqa: F401 (derive_features 供将来用)
from app.gmgn import fetch_market_cap, fetch_snapshot
from app.radar import RadarClient, parse_task

SnapshotFn = Callable[[str, str], dict]      # (chain, address) -> snapshot dict
MarketCapFn = Callable[[str, str], float]    # (chain, address) -> current market cap


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_entry_row(task: dict, snapshot: dict) -> dict:
    base = parse_task(task) or {}
    row: dict = dict(base)
    # GMGN 字段优先覆盖（更细），金狗雷达字段作回退
    for k in ("price", "liquidity", "market_cap", "volume_24h", "holder_count"):
        if snapshot.get(k) is not None:
            row[k] = snapshot[k]
    for k in ("top10_rate", "dev_hold_rate", "rat_rate", "entrapment_rate",
              "bundler_rate", "fresh_wallet_rate", "bot_degen_rate",
              "smart_wallets", "kol_wallets", "is_honeypot", "rug_ratio",
              "buy_tax", "sell_tax", "open_source", "owner_renounced", "burn_status"):
        row[k] = snapshot.get(k)
    if row.get("top10_rate") is None and base.get("top10_position") is not None:
        row["top10_rate"] = base["top10_position"]
    if snapshot.get("creation_timestamp") is not None:
        row["creation_timestamp"] = snapshot["creation_timestamp"]
    # 派生
    metrics = derive_metrics(row)
    row["turnover"] = metrics["turnover"]
    row["avg_holding_usd"] = metrics["avg_holding_usd"]
    # 追踪基准
    row["base_market_cap"] = row.get("market_cap")
    row["track_status"] = "tracking"
    row["gmgn_ok"] = 1 if snapshot.get("gmgn_ok") else 0
    return row


def process_new_task(db: Database, task: dict, snapshot_fn: SnapshotFn) -> None:
    base = parse_task(task)
    if not base:
        return
    if db.exists(base["task_id"]):
        return
    snapshot = snapshot_fn(base["chain"], base["address"])
    row = build_entry_row(task, snapshot)
    db.insert_entry(row)


def refresh_one(db: Database, task_id: str, market_cap_fn: MarketCapFn,
                track_hours: int, chain: str, address: str) -> None:
    row = db.get(task_id)
    if not row:
        return
    pushed = _parse_iso(row.get("pushed_at"))
    expired = False
    if pushed is not None:
        age_h = (datetime.now(timezone.utc) - pushed).total_seconds() / 3600
        if age_h >= track_hours:
            expired = True
    mc = market_cap_fn(chain, address)
    if mc is not None and mc > 0:
        db.update_price(task_id, current_market_cap=mc)
    if expired:
        db.finalize(task_id)


class Collector:
    """两条线程循环：发现新币 + 刷新价格。"""

    def __init__(self, settings: Settings, db: Database):
        self.s = settings
        self.db = db
        self._stop = threading.Event()
        self._client = RadarClient(settings.radar_base_url, settings.radar_username, settings.radar_password)

    def _snapshot_fn(self, chain: str, address: str) -> dict:
        return fetch_snapshot(self.s.gmgn_cli, chain, address)

    def _market_cap_fn(self, chain: str, address: str) -> float:
        return fetch_market_cap(self.s.gmgn_cli, chain, address)

    def discover_loop(self) -> None:
        self._client.login()
        while not self._stop.is_set():
            try:
                for task in self._client.fetch_completed_tasks():
                    base = parse_task(task)
                    if base and base["chain"] in self.s.chains:
                        process_new_task(self.db, task, self._snapshot_fn)
            except Exception as e:  # 单次失败不致命
                print(f"[discover] error: {e}")
            self._stop.wait(self.s.discover_interval)

    def price_loop(self) -> None:
        while not self._stop.is_set():
            try:
                for tid in self.db.tracking_ids():
                    row = self.db.get(tid)
                    if not row:
                        continue
                    refresh_one(self.db, tid, self._market_cap_fn,
                                self.s.track_hours, row.get("chain") or "", row.get("address") or "")
            except Exception as e:
                print(f"[price] error: {e}")
            self._stop.wait(self.s.price_interval)

    def run(self) -> None:
        t1 = threading.Thread(target=self.discover_loop, daemon=True)
        t2 = threading.Thread(target=self.price_loop, daemon=True)
        t1.start(); t2.start()
        return None

    def stop(self) -> None:
        self._stop.set()
