"""PostgreSQL version of Database — drop-in replacement for db.py when DATABASE_URL is set."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

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
    "filter_type", "matched_rules", "can_not_sell", "is_blacklist",
]

# Types for CREATE TABLE; ALTER TABLE ADD COLUMN defaults to TEXT
_COL_TYPE: dict[str, str] = {
    "price": "DOUBLE PRECISION", "liquidity": "DOUBLE PRECISION",
    "market_cap": "DOUBLE PRECISION", "volume_24h": "DOUBLE PRECISION",
    "holder_count": "INTEGER", "top10_rate": "DOUBLE PRECISION",
    "dev_hold_rate": "DOUBLE PRECISION", "rat_rate": "DOUBLE PRECISION",
    "entrapment_rate": "DOUBLE PRECISION", "bundler_rate": "DOUBLE PRECISION",
    "fresh_wallet_rate": "DOUBLE PRECISION", "bot_degen_rate": "DOUBLE PRECISION",
    "smart_wallets": "INTEGER", "kol_wallets": "INTEGER",
    "turnover": "DOUBLE PRECISION", "avg_holding_usd": "DOUBLE PRECISION",
    "rug_ratio": "DOUBLE PRECISION", "buy_tax": "DOUBLE PRECISION",
    "sell_tax": "DOUBLE PRECISION", "gmgn_ok": "INTEGER",
    "base_market_cap": "DOUBLE PRECISION", "current_gain_pct": "DOUBLE PRECISION",
    "peak_gain_pct": "DOUBLE PRECISION", "max_drop_pct": "DOUBLE PRECISION",
    "final_gain_pct": "DOUBLE PRECISION", "peak_market_cap": "DOUBLE PRECISION",
    "min_market_cap": "DOUBLE PRECISION", "enrich_attempts": "INTEGER",
    "settlement_market_cap": "DOUBLE PRECISION", "settlement_gain_pct": "DOUBLE PRECISION",
    "can_not_sell": "INTEGER",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, url: str):
        self._url = url
        self._conn = self._connect()
        self._lock = threading.RLock()

    def _connect(self):
        conn = psycopg2.connect(self._url)
        conn.autocommit = False
        return conn

    def _cur(self) -> psycopg2.extras.RealDictCursor:
        try:
            if self._conn.closed:
                raise psycopg2.OperationalError("closed")
        except Exception:
            self._conn = self._connect()
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _exec(self, sql: str, params=None):
        try:
            cur = self._cur()
            cur.execute(sql, params)
            return cur
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            self._conn = self._connect()
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, params)
            return cur

    def init_schema(self) -> None:
        non_pk = [c for c in COLUMNS if c != "task_id"]
        col_defs = ",\n".join(
            f'"{c}" {_COL_TYPE.get(c, "TEXT")}' for c in non_pk
        )
        with self._lock:
            self._exec(f'''
                CREATE TABLE IF NOT EXISTS tokens (
                    "task_id" TEXT PRIMARY KEY,
                    {col_defs}
                )
            ''')
            cur = self._exec("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='tokens' AND table_schema='public'
            """)
            existing = {row["column_name"] for row in cur.fetchall()}
            for c in COLUMNS:
                if c not in existing:
                    t = _COL_TYPE.get(c, "TEXT")
                    self._exec(f'ALTER TABLE tokens ADD COLUMN IF NOT EXISTS "{c}" {t}')
            self._conn.commit()

    def exists(self, task_id: str) -> bool:
        with self._lock:
            cur = self._exec("SELECT 1 FROM tokens WHERE task_id=%s", (task_id,))
            return cur.fetchone() is not None

    def insert_entry(self, row: dict) -> None:
        data = {c: row.get(c) for c in COLUMNS}
        data["created_at"] = _now()
        data["updated_at"] = _now()
        cols = ", ".join(f'"{c}"' for c in COLUMNS)
        vals = ", ".join("%s" for _ in COLUMNS)
        update_set = ", ".join(
            f'"{c}" = EXCLUDED."{c}"' for c in COLUMNS if c != "task_id"
        )
        with self._lock:
            self._exec(
                f'INSERT INTO tokens ({cols}) VALUES ({vals}) '
                f'ON CONFLICT (task_id) DO UPDATE SET {update_set}',
                [data[c] for c in COLUMNS],
            )
            self._conn.commit()

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._exec("SELECT * FROM tokens WHERE task_id=%s", (task_id,))
            r = cur.fetchone()
            return dict(r) if r else None

    def all(self) -> list[dict]:
        with self._lock:
            cur = self._exec("SELECT * FROM tokens ORDER BY pushed_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def all_backtested(self) -> list[dict]:
        with self._lock:
            cur = self._exec(
                "SELECT * FROM tokens WHERE backtest_id IS NOT NULL ORDER BY pushed_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]

    def tracking_ids(self) -> list[str]:
        with self._lock:
            cur = self._exec("SELECT task_id FROM tokens WHERE track_status='tracking'")
            return [r["task_id"] for r in cur.fetchall()]

    def enrichment_ids(self, limit: int = 50) -> list[str]:
        """Return recent rows whose GMGN snapshot still needs collection."""
        with self._lock:
            cur = self._exec(
                """SELECT task_id FROM tokens
                   WHERE address IS NOT NULL
                     AND COALESCE(enrich_attempts, 0) < 5
                     AND (
                       COALESCE(gmgn_ok, 0) = 0
                       OR (chain = 'sol' AND renounced_mint IS NULL)
                     )
                   ORDER BY pushed_at DESC
                   LIMIT %s""",
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
            self._exec(
                """UPDATE tokens SET current_gain_pct=%s, peak_gain_pct=%s, max_drop_pct=%s,
                   peak_market_cap=%s, min_market_cap=%s, last_priced_at=%s, updated_at=%s
                   WHERE task_id=%s""",
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
            sets = ", ".join(f'"{k}"=%s' for k in clean)
            vals = list(clean.values()) + [task_id]
            self._exec(f"UPDATE tokens SET {sets} WHERE task_id=%s", vals)
            self._conn.commit()

    def finalize(self, task_id: str) -> None:
        with self._lock:
            row = self.get(task_id)
            if not row:
                return
            self._exec(
                "UPDATE tokens SET final_gain_pct=%s, track_status='done', updated_at=%s WHERE task_id=%s",
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
        with self._lock:
            sets = [f'"{k}"=%s' for k in self.GMGN_FIELDS] + ['"gmgn_ok"=%s', '"updated_at"=%s']
            vals = [snap.get(k) for k in self.GMGN_FIELDS] + [1 if snap.get("gmgn_ok") else 0, _now(), task_id]
            self._exec(f"UPDATE tokens SET {','.join(sets)} WHERE task_id=%s", vals)
            self._conn.commit()

    def update_grade(self, task_id: str, grade: str) -> None:
        with self._lock:
            self._exec(
                "UPDATE tokens SET grade=%s, updated_at=%s WHERE task_id=%s",
                (grade, _now(), task_id),
            )
            self._conn.commit()

    def bump_enrich(self, task_id: str) -> None:
        with self._lock:
            self._exec(
                "UPDATE tokens SET enrich_attempts = COALESCE(enrich_attempts, 0) + 1 WHERE task_id=%s",
                (task_id,),
            )
            self._conn.commit()

    def mark_filtered(self, task_id: str, filter_type: str, matched_rules: list[str], snap: dict) -> None:
        import json
        with self._lock:
            self._exec(
                """UPDATE tokens
                   SET filter_type=%s, matched_rules=%s, gmgn_ok=%s,
                       track_status='done', updated_at=%s
                   WHERE task_id=%s""",
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
                cur = self._exec(
                    "SELECT * FROM tokens WHERE filter_type IS NOT NULL AND chain=%s"
                    " ORDER BY pushed_at DESC LIMIT %s",
                    (chain, limit),
                )
            else:
                cur = self._exec(
                    "SELECT * FROM tokens WHERE filter_type IS NOT NULL"
                    " ORDER BY pushed_at DESC LIMIT %s",
                    (limit,),
                )
            return [dict(r) for r in cur.fetchall()]

    def clear_filter(self, task_id: str) -> None:
        with self._lock:
            self._exec(
                "UPDATE tokens SET filter_type=NULL, matched_rules=NULL, track_status='tracking', updated_at=%s WHERE task_id=%s",
                (_now(), task_id),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
