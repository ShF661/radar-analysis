"""One-shot price update: refresh market caps and backtest metrics for all tracking tokens."""
from __future__ import annotations
import sys
import os


def _load_env() -> None:
    from pathlib import Path
    f = Path(".env")
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    _load_env()
    from app.config import load_settings
    from app.db_pg import Database
    from app.collector import Collector, refresh_one

    settings = load_settings()
    if not settings.database_url:
        print("[price] DATABASE_URL not set", flush=True)
        sys.exit(1)

    db = Database(settings.database_url)
    db.init_schema()
    c = Collector(settings, db)

    try:
        c._client.login()
    except Exception as e:
        print(f"[price] radar login failed (will skip backtest): {e}", flush=True)

    count = 0
    enrich_attempted = 0
    enrich_succeeded = 0
    try:
        tracking_ids = set(db.tracking_ids())
        enrich_limit = int(os.getenv("GMGN_ENRICH_LIMIT", "50"))
        enrich_ids = db.enrichment_ids(limit=enrich_limit, max_attempts=20)
        # Missing snapshots are processed even when backtest has already marked
        # the token done. dict.fromkeys keeps the newest enrichment order.
        task_ids = list(dict.fromkeys(enrich_ids + list(tracking_ids)))

        for tid in task_ids:
            row = db.get(tid)
            if not row:
                continue

            if tid in enrich_ids:
                enrich_attempted += 1
                snap = c._snapshot_fn(row.get("chain") or "", row.get("address") or "")
                if snap.get("gmgn_ok"):
                    db.update_snapshot(tid, snap)
                    enrich_succeeded += 1
                    print(f"[price] re-enriched {row.get('symbol')}", flush=True)
                db.bump_enrich(tid)

            if tid not in tracking_ids:
                continue

            bt = c._backtest_fn(row.get("chain") or "", row.get("address") or "", row.get("pushed_at"))
            if bt:
                db.apply_backtest_metrics(tid, bt)

            refresh_one(
                db, tid, c._market_cap_fn,
                settings.track_hours,
                row.get("chain") or "",
                row.get("address") or "",
            )
            count += 1
    finally:
        c._client.close()
        db.close()

    print(
        f"[price] done, updated={count} enrich_attempted={enrich_attempted} "
        f"enrich_succeeded={enrich_succeeded} enrich_failed={enrich_attempted - enrich_succeeded}",
        flush=True,
    )
    if enrich_attempted and enrich_succeeded == 0:
        print("[price] all GMGN enrichment attempts failed", file=sys.stderr, flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
