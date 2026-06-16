from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable

from app.config import Settings
from app.db import Database
from app.features import derive_metrics
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
    # 推送时字段（价格/流动性/市值/成交量/持有人）优先用金狗雷达的“推送瞬间”值，
    # GMGN 只在金狗雷达缺失时兜底——因为 GMGN 返回的是“当前”值，不是推送时值。
    for k in ("price", "liquidity", "market_cap", "volume_24h", "holder_count"):
        if row.get(k) is None and snapshot.get(k) is not None:
            row[k] = snapshot[k]
    # 细分指标（钱包构成/安全）只有 GMGN 有，直接取。
    for k in ("top10_rate", "dev_hold_rate", "rat_rate", "entrapment_rate",
              "bundler_rate", "fresh_wallet_rate", "bot_degen_rate",
              "smart_wallets", "kol_wallets", "is_honeypot", "rug_ratio",
              "buy_tax", "sell_tax", "open_source", "owner_renounced", "burn_status",
              "renounced_mint", "renounced_freeze"):
        row[k] = snapshot.get(k)
    if row.get("top10_rate") is None and base.get("top10_position") is not None:
        row["top10_rate"] = base["top10_position"]
    if row.get("creation_timestamp") is None and snapshot.get("creation_timestamp") is not None:
        row["creation_timestamp"] = snapshot["creation_timestamp"]
    # 派生
    metrics = derive_metrics(row)
    row["turnover"] = metrics["turnover"]
    row["avg_holding_usd"] = metrics["avg_holding_usd"]
    # 追踪基准 = 推送时市值
    row["base_market_cap"] = row.get("market_cap")
    row["track_status"] = "tracking"
    row["gmgn_ok"] = 1 if snapshot.get("gmgn_ok") else 0
    # 推送那一刻涨跌幅本就是 0；初始化后新币立刻可在涨跌幅维度可见，之后价格循环更新
    if row.get("base_market_cap"):
        row["current_gain_pct"] = 0.0
        row["peak_gain_pct"] = 0.0
        row["max_drop_pct"] = 0.0
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
        latest = db.get(task_id)
        # 只在拿到过真实涨幅时才定格；从未定价成功的不 finalize（下轮继续尝试），避免写入 NULL/陈旧值
        if latest and latest.get("current_gain_pct") is not None:
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
                    if not base or base["chain"] not in self.s.chains:
                        continue
                    if self.db.exists(base["task_id"]):
                        continue
                    process_new_task(self.db, task, self._snapshot_fn)
                    print(f"[discover] saved {base.get('symbol')} ({base['chain']}) task={base['task_id']}", flush=True)
                    self._stop.wait(self.s.gmgn_delay)
            except Exception as e:  # 单次失败不致命
                print(f"[discover] error: {e}", flush=True)
                try:
                    self._client.login()  # 会话可能过期，重新登录后下轮恢复
                except Exception as e2:
                    print(f"[discover] relogin failed: {e2}", flush=True)
            self._stop.wait(self.s.discover_interval)

    def price_loop(self) -> None:
        while not self._stop.is_set():
            try:
                for tid in self.db.tracking_ids():
                    row = self.db.get(tid)
                    if not row:
                        continue
                    # 自愈：之前没抓到 GMGN 细分指标的，重试补齐（最多 5 次，避免对 GMGN 无数据的币无限重试）
                    needs = not row.get("gmgn_ok") or (row.get("chain") == "sol" and row.get("renounced_mint") is None)
                    if needs and (row.get("enrich_attempts") or 0) < 5:
                        snap = self._snapshot_fn(row.get("chain") or "", row.get("address") or "")
                        if snap.get("gmgn_ok"):
                            self.db.update_snapshot(tid, snap)
                            print(f"[price] re-enriched {row.get('symbol')}", flush=True)
                        self.db.bump_enrich(tid)
                        self._stop.wait(self.s.gmgn_delay)
                    refresh_one(self.db, tid, self._market_cap_fn,
                                self.s.track_hours, row.get("chain") or "", row.get("address") or "")
                    self._stop.wait(self.s.gmgn_delay)
            except Exception as e:
                print(f"[price] error: {e}", flush=True)
            self._stop.wait(self.s.price_interval)

    def run(self) -> None:
        t1 = threading.Thread(target=self.discover_loop, daemon=True)
        t2 = threading.Thread(target=self.price_loop, daemon=True)
        t1.start(); t2.start()
        return None

    def stop(self) -> None:
        self._stop.set()
