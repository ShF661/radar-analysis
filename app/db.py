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
    "owner_renounced", "burn_status", "gmgn_ok", "base_market_cap",
    "current_gain_pct", "peak_gain_pct", "max_drop_pct", "final_gain_pct",
    "peak_market_cap", "min_market_cap", "track_status", "last_priced_at",
    "created_at", "updated_at",
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

    def tracking_ids(self) -> list[str]:
        with self._lock:
            cur = self._conn.execute("SELECT task_id FROM tokens WHERE track_status='tracking'")
            return [r["task_id"] for r in cur.fetchall()]

    def update_price(self, task_id: str, current_market_cap: float) -> None:
        with self._lock:
            row = self.get(task_id)
            if not row:
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
        "owner_renounced", "burn_status",
    ]

    def update_snapshot(self, task_id: str, snap: dict) -> None:
        """补齐之前没抓到的 GMGN 细分指标；不触碰价格追踪与推送时字段。"""
        with self._lock:
            sets = [f'"{k}"=?' for k in self.GMGN_FIELDS] + ['"gmgn_ok"=?', '"updated_at"=?']
            vals = [snap.get(k) for k in self.GMGN_FIELDS] + [1 if snap.get("gmgn_ok") else 0, _now(), task_id]
            self._conn.execute(f"UPDATE tokens SET {','.join(sets)} WHERE task_id=?", vals)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
