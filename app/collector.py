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
from app.signal_filter import run_filter
from app.signal_filter_store import load_config

SnapshotFn = Callable[[str, str], dict]
MarketCapFn = Callable[[str, str], float]
BacktestFn = Callable[[str, str, str | None], dict | None]


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _merge_backtest_metrics(row: dict, backtest: dict | None) -> None:
    if not backtest:
        return
    for k in (
        "backtest_id",
        "base_market_cap",
        "peak_market_cap",
        "peak_gain_pct",
        "max_drop_pct",
        "min_market_cap",
        "settlement_market_cap",
        "settlement_gain_pct",
    ):
        if backtest.get(k) is not None:
            row[k] = backtest[k]
    if backtest.get("status"):
        row["backtest_status"] = backtest["status"]
        row["track_status"] = "done" if backtest["status"] == "settled" else "tracking"
    if backtest.get("settlement_gain_pct") is not None:
        row["current_gain_pct"] = backtest["settlement_gain_pct"]
        if backtest.get("status") == "settled":
            row["final_gain_pct"] = backtest["settlement_gain_pct"]
    if backtest.get("last_market_at"):
        row["last_priced_at"] = backtest["last_market_at"]


def build_entry_row(task: dict, snapshot: dict, backtest: dict | None = None) -> dict:
    base = parse_task(task) or {}
    row: dict = dict(base)

    # GMGN is only a fallback for push-time token metrics, and remains the
    # source for wallet/security enrich fields.
    for k in ("price", "liquidity", "market_cap", "volume_24h", "holder_count"):
        if row.get(k) is None and snapshot.get(k) is not None:
            row[k] = snapshot[k]

    for k in (
        "top10_rate",
        "dev_hold_rate",
        "rat_rate",
        "entrapment_rate",
        "bundler_rate",
        "fresh_wallet_rate",
        "bot_degen_rate",
        "smart_wallets",
        "kol_wallets",
        "is_honeypot",
        "rug_ratio",
        "buy_tax",
        "sell_tax",
        "open_source",
        "owner_renounced",
        "burn_status",
        "renounced_mint",
        "renounced_freeze",
        "can_not_sell",
        "is_blacklist",
    ):
        row[k] = snapshot.get(k)

    if row.get("top10_rate") is None and base.get("top10_position") is not None:
        row["top10_rate"] = base["top10_position"]
    if row.get("creation_timestamp") is None and snapshot.get("creation_timestamp") is not None:
        row["creation_timestamp"] = snapshot["creation_timestamp"]

    metrics = derive_metrics(row)
    row["turnover"] = metrics["turnover"]
    row["avg_holding_usd"] = metrics["avg_holding_usd"]
    row["base_market_cap"] = row.get("market_cap")
    row["track_status"] = "tracking"
    row["gmgn_ok"] = 1 if snapshot.get("gmgn_ok") else 0

    _merge_backtest_metrics(row, backtest)

    if row.get("base_market_cap"):
        row["current_gain_pct"] = row.get("current_gain_pct") if row.get("current_gain_pct") is not None else 0.0
        row["peak_gain_pct"] = row.get("peak_gain_pct") if row.get("peak_gain_pct") is not None else 0.0
        row["max_drop_pct"] = row.get("max_drop_pct") if row.get("max_drop_pct") is not None else 0.0
    return row


def process_prefiltered_task(db: Database, task: dict) -> None:
    """Write a radar-backend-filtered task into tokens using API-provided metrics.

    These tasks have state=metric_filtered or safety_filtered — the radar backend
    already evaluated them and rejected them. We persist them so retrospective
    analysis can answer questions like "how accurate are our filter rules?"

    No GMGN call is made: all metric data comes from task.input.preanalysis.
    """
    base = parse_task(task)
    if not base:
        return
    if db.exists(base["task_id"]):
        return

    inp = task.get("input") or {}
    token_metrics: dict = (inp.get("token") or {}).get("metrics") or {}
    preanalysis: dict = inp.get("preanalysis") or {}
    security: dict = preanalysis.get("security") or {}
    pa_values: dict = {
        k: v.get("value")
        for k, v in ((preanalysis.get("metrics") or {}).get("values") or {}).items()
        if isinstance(v, dict)
    }

    row: dict = dict(base)

    # Push-time metrics: prefer preanalysis values (more carefully computed by radar)
    row["liquidity"]     = row.get("liquidity")    or token_metrics.get("liquidity")
    row["market_cap"]    = row.get("market_cap")   or token_metrics.get("market_cap")
    row["volume_24h"]    = row.get("volume_24h")   or token_metrics.get("volume_24h")
    row["holder_count"]  = pa_values.get("holder_count") or row.get("holder_count") or token_metrics.get("holder_count")
    row["top10_rate"]    = token_metrics.get("top10_position") or row.get("top10_position")

    # Wallet / behaviour rates from preanalysis
    row["dev_hold_rate"]    = pa_values.get("dev_team_hold_rate")  or token_metrics.get("gmgn_dev_hold_rate")
    row["bundler_rate"]     = pa_values.get("bundler_wallet_rate") or token_metrics.get("gmgn_cluster_rate")
    row["fresh_wallet_rate"]= pa_values.get("fresh_wallet_rate")   or token_metrics.get("gmgn_fresh_rate")
    row["entrapment_rate"]  = pa_values.get("entrapment_wallet_rate") or token_metrics.get("gmgn_phishing_rate")
    row["bot_degen_rate"]   = pa_values.get("bot_trading_rate")
    row["rat_rate"]         = pa_values.get("rat_trader_rate")
    row["smart_wallets"]    = pa_values.get("smart_wallet_count")
    row["kol_wallets"]      = pa_values.get("kol_wallet_count")
    row["avg_holding_usd"]  = pa_values.get("avg_holder_value")
    row["turnover"]         = pa_values.get("turnover_rate")

    # Security from preanalysis (renounced_freeze_account → renounced_freeze)
    row["renounced_mint"]   = security.get("renounced_mint")
    row["renounced_freeze"] = security.get("renounced_freeze_account")
    row["can_not_sell"]     = security.get("can_not_sell")

    row["base_market_cap"] = row.get("market_cap")
    row["track_status"]    = "done"
    # Treat preanalysis.available=True as equivalent to gmgn_ok for retrospective queries
    pa_ok = bool(preanalysis.get("security", {}).get("available") or preanalysis.get("metrics", {}).get("available"))
    row["gmgn_ok"] = 1 if pa_ok else 0

    db.insert_entry(row)

    # Derive filter_type and matched_rules from the radar filter_result
    filter_result: dict = task.get("filter_result") or {}
    state: str = task.get("state", "")
    filter_type = filter_result.get("type") or state.replace("_filtered", "")

    rule_name = filter_result.get("rule_name") or filter_result.get("reason") or ""
    conditions = filter_result.get("matched_conditions") or []
    if conditions:
        matched_rules = [
            f"{c.get('metric_label', c.get('metric_key', '?'))}({c.get('operator','?')}{c.get('threshold','?')},实际={round(c.get('actual_value', 0), 2)})"
            for c in conditions
        ]
    elif rule_name:
        matched_rules = [rule_name]
    else:
        matched_rules = []

    db.mark_filtered(base["task_id"], filter_type, matched_rules, {})

    print(
        f"[discover] pre-filtered {filter_type} {base.get('symbol')} ({base['chain']}) "
        f"rules={matched_rules} task={base['task_id']}",
        flush=True,
    )


def process_new_task(
    db: Database,
    task: dict,
    snapshot_fn: SnapshotFn,
    backtest_fn: BacktestFn | None = None,
    evo_db=None,
    filter_config: dict | None = None,
) -> None:
    base = parse_task(task)
    if not base:
        return
    if db.exists(base["task_id"]):
        return
    snapshot = snapshot_fn(base["chain"], base["address"])

    # Signal filter: safety + metric layers (before any further processing)
    if filter_config is not None:
        passes, filter_type, matched_rules = run_filter(base["chain"], snapshot, filter_config)
        if not passes:
            # Still insert a minimal row so the filtered task appears in the UI
            backtest = backtest_fn(base["chain"], base["address"], base.get("pushed_at")) if backtest_fn else None
            row = build_entry_row(task, snapshot, backtest)
            db.insert_entry(row)
            db.mark_filtered(base["task_id"], filter_type, matched_rules, snapshot)
            print(
                f"[filter] {filter_type} {base.get('symbol')} ({base['chain']}) "
                f"rules={matched_rules} task={base['task_id']}",
                flush=True,
            )
            return

    backtest = backtest_fn(base["chain"], base["address"], base.get("pushed_at")) if backtest_fn else None
    row = build_entry_row(task, snapshot, backtest)
    db.insert_entry(row)

    if evo_db is not None:
        from evolution.security import check_security
        passes, detail = check_security(base["chain"], snapshot)
        if passes:
            evo_db.insert_case(task, row)
        else:
            print(f"[evolution] security skip {base.get('symbol')}: {detail}", flush=True)


def refresh_one(
    db: Database,
    task_id: str,
    market_cap_fn: MarketCapFn,
    track_hours: int,
    chain: str,
    address: str,
) -> None:
    row = db.get(task_id)
    if not row:
        return
    pushed = _parse_iso(row.get("pushed_at"))
    expired = False
    if pushed is not None:
        age_h = (datetime.now(timezone.utc) - pushed).total_seconds() / 3600
        expired = age_h >= track_hours

    if row.get("backtest_id"):
        return

    mc = market_cap_fn(chain, address)
    if mc is not None and mc > 0:
        db.update_price(task_id, current_market_cap=mc)

    if expired:
        latest = db.get(task_id)
        if latest and latest.get("current_gain_pct") is not None:
            db.finalize(task_id)


class Collector:
    """Runs discovery and refresh loops for the feature-analysis database."""

    def __init__(self, settings: Settings, db: Database, evo_db=None):
        self.s = settings
        self.db = db
        self.evo_db = evo_db
        self._stop = threading.Event()
        self._client = RadarClient(settings.radar_base_url, settings.radar_username, settings.radar_password)

    def _snapshot_fn(self, chain: str, address: str) -> dict:
        return fetch_snapshot(self.s.gmgn_cli, chain, address)

    def _market_cap_fn(self, chain: str, address: str) -> float:
        return fetch_market_cap(self.s.gmgn_cli, chain, address)

    def _backtest_fn(self, chain: str, address: str, pushed_at: str | None) -> dict | None:
        return self._client.find_backtest_token(address, chain, pushed_at)

    def discover_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._client.login()
            except Exception as e:
                print(f"[discover] login failed: {e}, retrying in 60s", flush=True)
                self._stop.wait(60)
                continue
            while not self._stop.is_set():
                try:
                    for task in self._client.fetch_completed_tasks():
                        base = parse_task(task)
                        if not base or base["chain"] not in self.s.chains:
                            continue
                        if self.db.exists(base["task_id"]):
                            if base.get("grade"):
                                cur = self.db.get(base["task_id"])
                                if cur and not cur.get("grade"):
                                    self.db.update_grade(base["task_id"], base["grade"])
                            continue
                        process_new_task(
                            self.db, task, self._snapshot_fn, self._backtest_fn, self.evo_db,
                            filter_config=load_config(self.s.db_path),
                        )
                        print(f"[discover] saved {base.get('symbol')} ({base['chain']}) task={base['task_id']}", flush=True)
                        self._stop.wait(self.s.gmgn_delay)

                    for task in self._client.fetch_filtered_tasks():
                        base = parse_task(task)
                        if not base or base["chain"] not in self.s.chains:
                            continue
                        if self.db.exists(base["task_id"]):
                            continue
                        process_prefiltered_task(self.db, task)
                        self._stop.wait(self.s.gmgn_delay)
                except Exception as e:
                    print(f"[discover] error: {e}", flush=True)
                    break
                self._stop.wait(self.s.discover_interval)

    def price_loop(self) -> None:
        self._stop.wait(10)  # let discover_loop complete login first
        while not self._stop.is_set():
            try:
                for tid in self.db.tracking_ids():
                    row = self.db.get(tid)
                    if not row:
                        continue
                    needs = not row.get("gmgn_ok") or (row.get("chain") == "sol" and row.get("renounced_mint") is None)
                    if needs and (row.get("enrich_attempts") or 0) < 5:
                        snap = self._snapshot_fn(row.get("chain") or "", row.get("address") or "")
                        if snap.get("gmgn_ok"):
                            self.db.update_snapshot(tid, snap)
                            print(f"[price] re-enriched {row.get('symbol')}", flush=True)
                        self.db.bump_enrich(tid)
                        self._stop.wait(self.s.gmgn_delay)

                    bt = self._backtest_fn(row.get("chain") or "", row.get("address") or "", row.get("pushed_at"))
                    if bt:
                        self.db.apply_backtest_metrics(tid, bt)
                        self._stop.wait(self.s.gmgn_delay)

                    refresh_one(
                        self.db,
                        tid,
                        self._market_cap_fn,
                        self.s.track_hours,
                        row.get("chain") or "",
                        row.get("address") or "",
                    )
                    self._stop.wait(self.s.gmgn_delay)
            except Exception as e:
                print(f"[price] error: {e}", flush=True)
                if "401" in str(e):
                    try:
                        self._client.login()
                        print("[price] re-logged in after 401", flush=True)
                    except Exception as le:
                        print(f"[price] re-login failed: {le}", flush=True)
            self._stop.wait(self.s.price_interval)

    def run(self) -> None:
        t1 = threading.Thread(target=self.discover_loop, daemon=True)
        t2 = threading.Thread(target=self.price_loop, daemon=True)
        t1.start()
        t2.start()

    def stop(self) -> None:
        self._stop.set()
