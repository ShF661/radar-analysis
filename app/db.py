from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

COLUMNS = [
    "task_id", "token_key", "address", "chain", "symbol", "name", "pushed_at",
    "grade", "narrative", "price", "liquidity", "market_cap", "volume_24h",
    "holder_count", "top10_rate", "dev_hold_rate", "rat_rate", "entrapment_rate",
    "bundler_rate", "fresh_wallet_rate", "bot_degen_rate", "smart_wallets",
    "kol_wallets", "creation_timestamp", "turnover", "avg_holding_usd",
    "is_honeypot", "rug_ratio", "buy_tax", "sell_tax", "open_source",
    "owner_renounced", "burn_status", "renounced_mint", "renounced_freeze",
    "gmgn_ok", "base_market_cap",
    "current_gain_pct", "peak_gain_pct", "max_drop_pct", "final_gain_pct",
    "peak_market_cap", "min_market_cap", "track_status", "last_priced_at",
    "created_at", "updated_at", "enrich_attempts",
    "backtest_id", "backtest_status", "settlement_market_cap",
    "settlement_gain_pct",
    # signal filter
    "filter_type", "matched_rules", "can_not_sell", "is_blacklist",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def init_schema(self) -> None:
        cols_sql = ",\n".join(f'"{c}"' for c in COLUMNS if c != "task_id")
        with self._lock:
            self._conn.execute(
                f'CREATE TABLE IF NOT EXISTS tokens ("task_id" TEXT PRIMARY KEY, {cols_sql})'
            )
            # 字段迁移：为已存在的旧表补上新增列
            existing = {row[1] for row in self._conn.execute("PRAGMA table_info(tokens)")}
            for c in COLUMNS:
                if c not in existing:
                    self._conn.execute(f'ALTER TABLE tokens ADD COLUMN "{c}"')
            self._conn.commit()

    def exists(self, task_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM tokens WHERE task_id=?", (task_id,))
            return cur.fetchone() is not None

    def insert_entry(self, row: dict) -> None:
        data = {c: row.get(c) for c in COLUMNS}
        data["task_id"] = row["task_id"]
        data["created_at"] = _now()
        data["updated_at"] = _now()
        cols = ",".join(f'"{c}"' for c in COLUMNS)
        ph = ",".join("?" for _ in COLUMNS)
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO tokens ({cols}) VALUES ({ph})",
                [data[c] for c in COLUMNS],
            )
            self._conn.commit()

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM tokens WHERE task_id=?", (task_id,))
            r = cur.fetchone()
            return dict(r) if r else None

    def all(self) -> list[dict]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM tokens ORDER BY pushed_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def all_backtested(self) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM tokens WHERE backtest_id IS NOT NULL ORDER BY pushed_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]

    def tracking_ids(self) -> list[str]:
        with self._lock:
            cur = self._conn.execute("SELECT task_id FROM tokens WHERE track_status='tracking'")
            return [r["task_id"] for r in cur.fetchall()]

    def enrichment_ids(self, limit: int = 50) -> list[str]:
        """Return recent rows whose GMGN snapshot still needs collection."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT task_id FROM tokens
                   WHERE address IS NOT NULL
                     AND COALESCE(enrich_attempts, 0) < 5
                     AND (
                       COALESCE(gmgn_ok, 0) = 0
                       OR (chain = 'sol' AND renounced_mint IS NULL)
                     )
                   ORDER BY pushed_at DESC
                   LIMIT ?""",
                (limit,),
            )
            return [r["task_id"] for r in cur.fetchall()]

    def update_price(self, task_id: str, current_market_cap: float) -> None:
        with self._lock:
            row = self.get(task_id)
            if not row:
                return
            if row.get("backtest_id"):
                return
            base = row.get("base_market_cap")
            if not base:
                return
            gain = round((current_market_cap / base - 1) * 100, 10)
            peak_mc = max(current_market_cap, row.get("peak_market_cap") or current_market_cap)
            min_mc = min(current_market_cap, row.get("min_market_cap") or current_market_cap)
            peak_gain = round((peak_mc / base - 1) * 100, 10)
            drop = round(max(0.0, (1 - min_mc / base) * 100), 10)
            self._conn.execute(
                """UPDATE tokens SET current_gain_pct=?, peak_gain_pct=?, max_drop_pct=?,
                   peak_market_cap=?, min_market_cap=?, last_priced_at=?, updated_at=? WHERE task_id=?""",
                (gain, peak_gain, drop, peak_mc, min_mc, _now(), _now(), task_id),
            )
            self._conn.commit()

    def apply_backtest_metrics(self, task_id: str, metrics: dict) -> None:
        with self._lock:
            row = self.get(task_id)
            if not row:
                return
            updates = {
                "backtest_id": metrics.get("backtest_id"),
                "backtest_status": metrics.get("status"),
                "base_market_cap": metrics.get("base_market_cap"),
                "peak_market_cap": metrics.get("peak_market_cap"),
                "peak_gain_pct": metrics.get("peak_gain_pct"),
                "max_drop_pct": metrics.get("max_drop_pct"),
                "min_market_cap": metrics.get("min_market_cap"),
                "settlement_market_cap": metrics.get("settlement_market_cap"),
                "settlement_gain_pct": metrics.get("settlement_gain_pct"),
                "last_priced_at": metrics.get("last_market_at"),
            }
            settlement_gain = metrics.get("settlement_gain_pct")
            if settlement_gain is not None:
                updates["current_gain_pct"] = settlement_gain
                if metrics.get("status") == "settled":
                    updates["final_gain_pct"] = settlement_gain
            if metrics.get("status") == "settled":
                updates["track_status"] = "done"
            elif metrics.get("status"):
                updates["track_status"] = "tracking"
            clean = {k: v for k, v in updates.items() if v is not None}
            if not clean:
                return
            clean["updated_at"] = _now()
            sets = ",".join(f'"{k}"=?' for k in clean)
            vals = list(clean.values()) + [task_id]
            self._conn.execute(f"UPDATE tokens SET {sets} WHERE task_id=?", vals)
            self._conn.commit()

    def finalize(self, task_id: str) -> None:
        with self._lock:
            row = self.get(task_id)
            if not row:
                return
            self._conn.execute(
                "UPDATE tokens SET final_gain_pct=?, track_status='done', updated_at=? WHERE task_id=?",
                (row.get("current_gain_pct"), _now(), task_id),
            )
            self._conn.commit()

    GMGN_FIELDS = [
        "top10_rate", "dev_hold_rate", "rat_rate", "entrapment_rate", "bundler_rate",
        "fresh_wallet_rate", "bot_degen_rate", "smart_wallets", "kol_wallets",
        "is_honeypot", "rug_ratio", "buy_tax", "sell_tax", "open_source",
        "owner_renounced", "burn_status", "renounced_mint", "renounced_freeze",
        "can_not_sell", "is_blacklist",
    ]

    def update_snapshot(self, task_id: str, snap: dict) -> None:
        """补齐之前没抓到的 GMGN 细分指标；不触碰价格追踪与推送时字段。"""
        with self._lock:
            sets = [f'"{k}"=?' for k in self.GMGN_FIELDS] + ['"gmgn_ok"=?', '"updated_at"=?']
            vals = [snap.get(k) for k in self.GMGN_FIELDS] + [1 if snap.get("gmgn_ok") else 0, _now(), task_id]
            self._conn.execute(f"UPDATE tokens SET {','.join(sets)} WHERE task_id=?", vals)
            self._conn.commit()

    def update_grade(self, task_id: str, grade: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tokens SET grade=?, updated_at=? WHERE task_id=?", (grade, _now(), task_id)
            )
            self._conn.commit()

    def bump_enrich(self, task_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tokens SET enrich_attempts = COALESCE(enrich_attempts, 0) + 1 WHERE task_id=?",
                (task_id,),
            )
            self._conn.commit()

    def mark_filtered(self, task_id: str, filter_type: str, matched_rules: list[str], snap: dict) -> None:
        """Write filter outcome fields onto an existing row (called right after insert_entry)."""
        import json
        with self._lock:
            self._conn.execute(
                """UPDATE tokens
                   SET filter_type=?, matched_rules=?, gmgn_ok=?,
                       track_status='done', updated_at=?
                   WHERE task_id=?""",
                (
                    filter_type,
                    json.dumps(matched_rules, ensure_ascii=False),
                    1 if snap.get("gmgn_ok") else 0,
                    _now(),
                    task_id,
                ),
            )
            self._conn.commit()

    def get_filtered(self, limit: int = 50, chain: str | None = None) -> list[dict]:
        with self._lock:
            if chain:
                cur = self._conn.execute(
                    "SELECT * FROM tokens WHERE filter_type IS NOT NULL AND chain=?"
                    " ORDER BY pushed_at DESC LIMIT ?",
                    (chain, limit),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM tokens WHERE filter_type IS NOT NULL"
                    " ORDER BY pushed_at DESC LIMIT ?",
                    (limit,),
                )
            return [dict(r) for r in cur.fetchall()]

    def clear_filter(self, task_id: str) -> None:
        """Remove filter mark so the task can re-enter processing (rescue)."""
        with self._lock:
            self._conn.execute(
                "UPDATE tokens SET filter_type=NULL, matched_rules=NULL, track_status='tracking', updated_at=? WHERE task_id=?",
                (_now(), task_id),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
