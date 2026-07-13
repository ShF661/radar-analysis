from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

CN_TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_bool(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (bool, int)):
        return 1 if v else 0
    if isinstance(v, str):
        return 1 if v.lower() in ("yes", "true", "1") else 0
    return None


class EvolutionDB:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def init_schema(self) -> None:
        with self._lock:
            self._conn.execute("""
            CREATE TABLE IF NOT EXISTS evolution_cases (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                push_record_id        TEXT NOT NULL UNIQUE,
                token_address         TEXT NOT NULL,
                chain                 TEXT NOT NULL,
                symbol                TEXT,
                push_time             TEXT NOT NULL,
                push_market_cap       REAL,
                push_price            REAL,
                narrative_grade       TEXT,
                narrative_text        TEXT,
                narrative_hit         INTEGER,
                gain_24h_pct          REAL,
                top10_rate            REAL,
                prompt_input_snapshot TEXT,
                gmgn_ok               INTEGER DEFAULT 1,
                liquidity             REAL,
                volume_24h            REAL,
                holder_count          INTEGER,
                dev_hold_rate         REAL,
                smart_degen_count     INTEGER,
                renowned_count        INTEGER,
                bundler_rate          REAL,
                bot_degen_rate        REAL,
                fresh_wallet_rate     REAL,
                rat_trader_rate       REAL,
                entrapment_ratio      REAL,
                turnover_rate         REAL,
                avg_hold_amount       REAL,
                is_honeypot           INTEGER,
                rug_ratio             REAL,
                buy_tax               REAL,
                sell_tax              REAL,
                security_risk_detail  TEXT,
                flash_crash_detected  INTEGER,
                flash_crash_max_drop  REAL,
                flash_crash_time      TEXT,
                tags                  TEXT,
                is_failure_case       INTEGER,
                root_cause_category   TEXT,
                root_cause_detail     TEXT,
                is_prompt_optimizable INTEGER,
                prompt_issue          TEXT,
                filter_signals        TEXT,
                analysis_confidence   TEXT,
                analysis_status       TEXT DEFAULT 'pending',
                analyzed_at           TEXT,
                retry_count           INTEGER DEFAULT 0,
                last_error            TEXT,
                created_at            TEXT,
                updated_at            TEXT,
                filter_type           TEXT,
                matched_rules         TEXT
            )""")
            # Schema migration: add columns for existing tables
            existing = {row[1] for row in self._conn.execute("PRAGMA table_info(evolution_cases)")}
            for col, defn in [("filter_type", "TEXT"), ("matched_rules", "TEXT")]:
                if col not in existing:
                    self._conn.execute(f"ALTER TABLE evolution_cases ADD COLUMN {col} {defn}")
            self._conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_test_results (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                tested_at        TEXT,
                token_count      INTEGER,
                fail_group_count INTEGER,
                succ_group_count INTEGER,
                old_mismatch     INTEGER,
                new_mismatch     INTEGER,
                improvement_pct  REAL,
                retention_pct    REAL,
                conclusion       TEXT,
                applied          INTEGER,
                applied_at       TEXT,
                note             TEXT
            )""")
            self._conn.commit()

    # ── T+0 insert ──────────────────────────────────────────────────────────

    def insert_case(self, task: dict, row: dict) -> None:
        """Write a new evolution case from a radar task + merged collector row."""
        snap = (
            task.get("prompt_input_snapshot")
            or task.get("prompt_input")
            or (task.get("latest_score") or {}).get("prompt_input")
        )
        data = {
            "push_record_id":        row["task_id"],
            "token_address":         row["address"],
            "chain":                 row["chain"],
            "symbol":                row.get("symbol"),
            "push_time":             row["pushed_at"],
            "push_market_cap":       row.get("market_cap"),
            "push_price":            row.get("price"),
            "narrative_grade":       row.get("grade"),
            "narrative_text":        row.get("narrative"),
            "narrative_hit":         None,
            "gain_24h_pct":          None,
            "top10_rate":            row.get("top10_rate"),
            "prompt_input_snapshot": snap,
            "gmgn_ok":               1 if row.get("gmgn_ok") else 0,
            "liquidity":             row.get("liquidity"),
            "volume_24h":            row.get("volume_24h"),
            "holder_count":          row.get("holder_count"),
            "dev_hold_rate":         row.get("dev_hold_rate"),
            "smart_degen_count":     row.get("smart_wallets"),
            "renowned_count":        row.get("kol_wallets"),
            "bundler_rate":          row.get("bundler_rate"),
            "bot_degen_rate":        row.get("bot_degen_rate"),
            "fresh_wallet_rate":     row.get("fresh_wallet_rate"),
            "rat_trader_rate":       row.get("rat_rate"),
            "entrapment_ratio":      row.get("entrapment_rate"),
            "turnover_rate":         row.get("turnover"),
            "avg_hold_amount":       row.get("avg_holding_usd"),
            "is_honeypot":           _to_bool(row.get("is_honeypot")),
            "rug_ratio":             row.get("rug_ratio"),
            "buy_tax":               row.get("buy_tax"),
            "sell_tax":              row.get("sell_tax"),
            "security_risk_detail":  None,
            "analysis_status":       "pending",
            "retry_count":           0,
            "created_at":            _now(),
            "updated_at":            _now(),
        }
        cols = ", ".join(data.keys())
        ph   = ", ".join("?" for _ in data)
        with self._lock:
            self._conn.execute(
                f"INSERT OR IGNORE INTO evolution_cases ({cols}) VALUES ({ph})",
                list(data.values()),
            )
            self._conn.commit()

    # ── T+24h reads ─────────────────────────────────────────────────────────

    def pending_due(self, now_iso: str) -> list[dict]:
        """Cases ready for T+24h processing: ≥24h old, pending/failed, retry<3."""
        # SQLite datetime() uses space separator and cannot parse +00:00 offsets.
        # Normalize now_iso and push_time both to 'YYYY-MM-DD HH:MM:SS' for comparison.
        now_plain = now_iso[:19].replace("T", " ")
        with self._lock:
            cur = self._conn.execute("""
                SELECT * FROM evolution_cases
                WHERE analysis_status IN ('pending', 'failed')
                  AND retry_count < 3
                  AND replace(substr(push_time, 1, 19), 'T', ' ') <= datetime(?, '-24 hours')
            """, (now_plain,))
            return [dict(r) for r in cur.fetchall()]

    def is_trusted_signal(self, push_record_id: str) -> bool:
        """Trusted sample gate used before failure tagging.

        A trusted signal has GMGN enrichment, was not filtered, has a backtest
        row, and was ingested within 5 minutes of the radar push.
        """
        with self._lock:
            cur = self._conn.execute("""
                SELECT 1
                FROM tokens
                WHERE task_id = ?
                  AND COALESCE(gmgn_ok, 0) = 1
                  AND filter_type IS NULL
                  AND backtest_id IS NOT NULL
                  AND (
                    strftime('%s', replace(substr(created_at, 1, 19), 'T', ' ')) -
                    strftime('%s', replace(substr(pushed_at, 1, 19), 'T', ' '))
                  ) BETWEEN 0 AND 300
            """, (push_record_id,))
            return cur.fetchone() is not None

    def get_case(self, push_record_id: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM evolution_cases WHERE push_record_id = ?",
                (push_record_id,),
            )
            r = cur.fetchone()
            return dict(r) if r else None

    # ── T+24h writes ─────────────────────────────────────────────────────────

    def update_tagging(self, push_record_id: str, updates: dict) -> None:
        updates["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [push_record_id]
        with self._lock:
            self._conn.execute(
                f"UPDATE evolution_cases SET {sets} WHERE push_record_id = ?", vals
            )
            self._conn.commit()

    def mark_failed(self, push_record_id: str, error: str) -> None:
        with self._lock:
            self._conn.execute("""
                UPDATE evolution_cases
                SET analysis_status = 'failed',
                    last_error = ?,
                    retry_count = retry_count + 1,
                    updated_at = ?
                WHERE push_record_id = ?
            """, (error[:500], _now(), push_record_id))
            self._conn.commit()

    def mark_untrusted_skipped(self, push_record_id: str) -> None:
        """Keep untrusted pushed signals out of failure/problem labels."""
        with self._lock:
            self._conn.execute("""
                UPDATE evolution_cases
                SET analysis_status = 'skipped',
                    tags = '[]',
                    is_failure_case = 0,
                    analyzed_at = ?,
                    updated_at = ?
                WHERE push_record_id = ?
            """, (_now(), _now(), push_record_id))
            self._conn.commit()

    # ── Daily report reads ───────────────────────────────────────────────────

    def _day_window_utc(self, date_str: str) -> tuple[str, str]:
        """Return Beijing natural-day bounds as UTC plain strings for SQLite."""
        local_day = datetime.fromisoformat(date_str).date()
        start_local = datetime.combine(local_day, datetime.min.time(), tzinfo=CN_TZ)
        end_local = start_local + timedelta(days=1)
        now_local = datetime.now(CN_TZ)
        if end_local > now_local:
            end_local = now_local
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        return (
            start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def daily_stats(self, date_str: str, backtest_ids: set | None = None) -> dict:
        """Daily report stats for tokens pushed during Beijing date_str.

        backtest_ids: when provided, only tokens whose backtest_id is in this set are counted.
        """
        start, end = self._day_window_utc(date_str)
        now_minus_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        bt_filter = ""
        bt_params: tuple = ()
        if backtest_ids:
            placeholders = ",".join("?" * len(backtest_ids))
            bt_filter = f"AND t.backtest_id IN ({placeholders})"
            bt_params = tuple(backtest_ids)
        with self._lock:
            cur = self._conn.execute(f"""
                WITH day_tokens AS (
                    SELECT
                        t.*,
                        replace(substr(t.pushed_at, 1, 19), 'T', ' ') AS pushed_plain,
                        CASE
                            WHEN COALESCE(t.gmgn_ok, 0) = 1
                             AND t.filter_type IS NULL
                             AND t.backtest_id IS NOT NULL
                             AND (
                                strftime('%s', replace(substr(t.created_at, 1, 19), 'T', ' ')) -
                                strftime('%s', replace(substr(t.pushed_at, 1, 19), 'T', ' '))
                             ) BETWEEN 0 AND 300
                            THEN 1 ELSE 0
                        END AS trusted
                    FROM tokens t
                    WHERE replace(substr(t.pushed_at, 1, 19), 'T', ' ') >= ?
                      AND replace(substr(t.pushed_at, 1, 19), 'T', ' ') < ?
                      {bt_filter}
                )
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN trusted = 1 THEN 1 ELSE 0 END) AS trusted_total,
                    SUM(CASE WHEN peak_gain_pct IS NOT NULL THEN 1 ELSE 0 END) AS gain_sample_all,
                    SUM(CASE WHEN trusted = 1 AND peak_gain_pct IS NOT NULL THEN 1 ELSE 0 END) AS gain_sample_total,
                    SUM(CASE WHEN peak_gain_pct >= 100 THEN 1 ELSE 0 END) AS gain_100,
                    SUM(CASE WHEN peak_gain_pct >= 50 THEN 1 ELSE 0 END) AS high_gain,
                    SUM(CASE WHEN trusted = 1 AND peak_gain_pct < 50 THEN 1 ELSE 0 END) AS low_gain,
                    SUM(CASE WHEN trusted = 1 AND e.flash_crash_detected = 1 THEN 1 ELSE 0 END) AS flash_crash,
                    SUM(CASE
                        WHEN trusted = 1 AND (
                            dt.is_honeypot IN ('yes', 'true', '1', 1)
                            OR dt.can_not_sell = 1
                            OR dt.is_blacklist IN ('yes', 'true', '1', 1)
                            OR COALESCE(dt.rug_ratio, 0) > 0.3
                            OR COALESCE(dt.buy_tax, 0) > 10
                            OR COALESCE(dt.sell_tax, 0) > 10
                        )
                        THEN 1 ELSE 0
                    END) AS security_risk,
                    SUM(CASE
                        WHEN trusted = 1
                         AND pushed_plain <= ?
                         AND e.narrative_hit = 0
                        THEN 1 ELSE 0
                    END) AS grade_mismatch
                FROM day_tokens dt
                LEFT JOIN evolution_cases e ON e.push_record_id = dt.task_id
            """, (start, end) + bt_params + (now_minus_24h,))
            row = dict(cur.fetchone())
            all_total = row.get("gain_sample_all") or 0
            trusted_total = row.get("gain_sample_total") or 0
            row["win_rate"] = (row.get("gain_100") or 0) / all_total if all_total else 0.0
            row["high_gain_rate"] = (row.get("high_gain") or 0) / all_total if all_total else 0.0
            row["low_gain_rate"] = (row.get("low_gain") or 0) / trusted_total if trusted_total else 0.0
            return row

    def security_risk_cases_today(self, date_str: str, backtest_ids: set | None = None) -> list[dict]:
        """Trusted security-risk cases pushed during Beijing date_str."""
        start, end = self._day_window_utc(date_str)
        bt_filter = ""
        bt_params: tuple = ()
        if backtest_ids:
            placeholders = ",".join("?" * len(backtest_ids))
            bt_filter = f"AND backtest_id IN ({placeholders})"
            bt_params = tuple(backtest_ids)
        with self._lock:
            cur = self._conn.execute(f"""
                SELECT symbol, chain, is_honeypot, rug_ratio, buy_tax, sell_tax,
                       NULL AS security_risk_detail
                FROM tokens
                WHERE replace(substr(pushed_at, 1, 19), 'T', ' ') >= ?
                  AND replace(substr(pushed_at, 1, 19), 'T', ' ') < ?
                  AND COALESCE(gmgn_ok, 0) = 1
                  AND filter_type IS NULL
                  AND backtest_id IS NOT NULL
                  AND (
                    strftime('%s', replace(substr(created_at, 1, 19), 'T', ' ')) -
                    strftime('%s', replace(substr(pushed_at, 1, 19), 'T', ' '))
                  ) BETWEEN 0 AND 300
                  {bt_filter}
                  AND (
                    is_honeypot IN ('yes', 'true', '1', 1)
                    OR can_not_sell = 1
                    OR is_blacklist IN ('yes', 'true', '1', 1)
                    OR COALESCE(rug_ratio, 0) > 0.3
                    OR COALESCE(buy_tax, 0) > 10
                    OR COALESCE(sell_tax, 0) > 10
                  )
            """, (start, end) + bt_params)
            return [dict(r) for r in cur.fetchall()]

    def failure_cases_today(self, date_str: str, backtest_ids: set | None = None) -> list[dict]:
        """Trusted problem cases pushed during Beijing date_str."""
        import json

        start, end = self._day_window_utc(date_str)
        now_minus_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        bt_filter = ""
        bt_params: tuple = ()
        if backtest_ids:
            placeholders = ",".join("?" * len(backtest_ids))
            bt_filter = f"AND t.backtest_id IN ({placeholders})"
            bt_params = tuple(backtest_ids)
        with self._lock:
            cur = self._conn.execute(f"""
                SELECT
                    t.task_id AS push_record_id,
                    t.symbol,
                    t.chain,
                    t.grade AS narrative_grade,
                    t.narrative AS narrative_text,
                    t.peak_gain_pct,
                    t.max_drop_pct,
                    t.liquidity,
                    t.holder_count,
                    t.smart_wallets,
                    t.kol_wallets,
                    t.rug_ratio,
                    t.buy_tax,
                    t.sell_tax,
                    t.is_honeypot,
                    t.can_not_sell,
                    t.is_blacklist,
                    replace(substr(t.pushed_at, 1, 19), 'T', ' ') AS pushed_plain,
                    e.narrative_hit,
                    e.flash_crash_detected,
                    e.flash_crash_max_drop,
                    e.root_cause_category,
                    e.root_cause_detail,
                    e.is_prompt_optimizable,
                    e.prompt_issue,
                    e.filter_signals,
                    e.analysis_confidence
                FROM tokens t
                LEFT JOIN evolution_cases e ON e.push_record_id = t.task_id
                WHERE replace(substr(t.pushed_at, 1, 19), 'T', ' ') >= ?
                  AND replace(substr(t.pushed_at, 1, 19), 'T', ' ') < ?
                  AND COALESCE(t.gmgn_ok, 0) = 1
                  AND t.filter_type IS NULL
                  AND t.backtest_id IS NOT NULL
                  AND (
                    strftime('%s', replace(substr(t.created_at, 1, 19), 'T', ' ')) -
                    strftime('%s', replace(substr(t.pushed_at, 1, 19), 'T', ' '))
                  ) BETWEEN 0 AND 300
                  {bt_filter}
            """, (start, end) + bt_params)
            rows = []
            for r in cur.fetchall():
                row = dict(r)
                tags: list[str] = []
                signals: list[str] = []
                if row.get("flash_crash_detected") == 1:
                    tags.append("flash_crash")
                    drop = row.get("flash_crash_max_drop")
                    if drop is not None:
                        signals.append(f"5分钟K线最大跌幅 {abs(float(drop)):.1f}%")
                if row.get("peak_gain_pct") is not None and float(row["peak_gain_pct"]) < 50:
                    tags.append("low_gain")
                    signals.append(f"推荐后最高涨幅仅 {float(row['peak_gain_pct']):.1f}%")
                security_hit = (
                    str(row.get("is_honeypot")).lower() in ("yes", "true", "1")
                    or row.get("can_not_sell") == 1
                    or str(row.get("is_blacklist")).lower() in ("yes", "true", "1")
                    or (row.get("rug_ratio") is not None and float(row["rug_ratio"]) > 0.3)
                    or (row.get("buy_tax") is not None and float(row["buy_tax"]) > 10)
                    or (row.get("sell_tax") is not None and float(row["sell_tax"]) > 10)
                )
                if security_hit:
                    tags.append("security_risk")
                    signals.append("安全字段命中风险")
                if row.get("pushed_plain") <= now_minus_24h and row.get("narrative_hit") == 0:
                    tags.append("grade_mismatch")
                if not tags:
                    continue
                stored_signals = []
                try:
                    stored_signals = json.loads(row.get("filter_signals") or "[]")
                except json.JSONDecodeError:
                    pass
                row["tags"] = json.dumps(tags, ensure_ascii=False)
                row["filter_signals"] = json.dumps((stored_signals or []) + signals, ensure_ascii=False)
                row["is_failure_case"] = 1
                rows.append(row)
            return rows

    def flash_crash_pending(self, date_str: str,
                            backtest_ids: set | None = None,
                            min_age_hours: int = 1) -> list[dict]:
        """Trusted cases pushed on date_str, >= min_age_hours ago, that need (re-)scanning.

        Includes:
        - flash_crash_detected IS NULL  (never scanned)
        - flash_crash_detected = 0 AND push_time + 24h not yet reached
          (scanned before crash happened, still within window)
        """
        start, end = self._day_window_utc(date_str)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=min_age_hours)).strftime("%Y-%m-%d %H:%M:%S")
        final_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        bt_filter = ""
        bt_params: tuple = ()
        if backtest_ids:
            placeholders = ",".join("?" * len(backtest_ids))
            bt_filter = f"AND t.backtest_id IN ({placeholders})"
            bt_params = tuple(backtest_ids)
        with self._lock:
            cur = self._conn.execute(f"""
                SELECT e.push_record_id, e.chain, e.token_address, e.push_time
                FROM evolution_cases e
                JOIN tokens t ON t.task_id = e.push_record_id
                WHERE replace(substr(e.push_time, 1, 19), 'T', ' ') >= ?
                  AND replace(substr(e.push_time, 1, 19), 'T', ' ') < ?
                  AND replace(substr(e.push_time, 1, 19), 'T', ' ') <= ?
                  AND (
                    e.flash_crash_detected IS NULL
                    OR (
                      e.flash_crash_detected = 0
                      AND replace(substr(e.push_time, 1, 19), 'T', ' ') > ?
                    )
                  )
                  AND COALESCE(t.gmgn_ok, 0) = 1
                  AND t.filter_type IS NULL
                  AND t.backtest_id IS NOT NULL
                  AND (
                    strftime('%s', replace(substr(t.created_at, 1, 19), 'T', ' ')) -
                    strftime('%s', replace(substr(t.pushed_at, 1, 19), 'T', ' '))
                  ) BETWEEN 0 AND 300
                  {bt_filter}
            """, (start, end, cutoff, final_cutoff) + bt_params)
            return [dict(r) for r in cur.fetchall()]

    def update_flash_crash(self, push_record_id: str, detected: int,
                           max_drop: float | None, crash_ts: str | None) -> None:
        """Write flash crash detection result without touching other fields."""
        with self._lock:
            self._conn.execute("""
                UPDATE evolution_cases
                SET flash_crash_detected = ?,
                    flash_crash_max_drop  = ?,
                    flash_crash_time      = ?,
                    updated_at            = ?
                WHERE push_record_id = ?
            """, (detected, max_drop, crash_ts, _now(), push_record_id))
            self._conn.commit()

    def filtered_cases_today(self, date_str: str) -> list[dict]:
        """Return tokens filtered by metric or safety rules pushed during Beijing date_str.

        Reads from `tokens` table directly — filtered tokens never enter evolution_cases.
        matched_rules is stored as a JSON array string and is decoded here.
        """
        import json as _json
        start, end = self._day_window_utc(date_str)
        with self._lock:
            cur = self._conn.execute("""
                SELECT symbol, chain, address, filter_type, matched_rules,
                       liquidity, holder_count, top10_rate, bundler_rate,
                       dev_hold_rate, fresh_wallet_rate
                FROM tokens
                WHERE replace(substr(pushed_at, 1, 19), 'T', ' ') >= ?
                  AND replace(substr(pushed_at, 1, 19), 'T', ' ') < ?
                  AND filter_type IS NOT NULL
                ORDER BY pushed_at DESC
            """, (start, end))
            rows = []
            for r in cur.fetchall():
                row = dict(r)
                raw = row.get("matched_rules") or "[]"
                try:
                    rules = _json.loads(raw)
                    row["matched_rules"] = rules if isinstance(rules, list) else [raw]
                except (_json.JSONDecodeError, TypeError):
                    row["matched_rules"] = [raw] if raw else []
                rows.append(row)
            return rows

    def cases_for_prompt_test(self, days: int = 30) -> list[dict]:
        """Cases for prompt batch test: has narrative_hit and prompt_input_snapshot."""
        with self._lock:
            cur = self._conn.execute("""
                SELECT push_record_id, symbol, narrative_grade, narrative_hit,
                       prompt_input_snapshot
                FROM evolution_cases
                WHERE push_time >= datetime('now', ? || ' days')
                  AND narrative_hit IS NOT NULL
                  AND prompt_input_snapshot IS NOT NULL
                  AND gmgn_ok = 1
            """, (f"-{days}",))
            return [dict(r) for r in cur.fetchall()]

    def insert_prompt_test_result(self, result: dict) -> None:
        cols = ", ".join(result.keys())
        ph   = ", ".join("?" for _ in result)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO prompt_test_results ({cols}) VALUES ({ph})",
                list(result.values()),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
