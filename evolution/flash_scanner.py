"""
Independent flash crash scanner — runs every 30 minutes via Task Scheduler.

Only scans today's trusted samples from the TG测试频道 (pub-tgpush-a7d75xtu)
that were pushed >= 1h ago and haven't had flash crash detection yet.

  python -m evolution.flash_scanner
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

TARGET_CHANNEL_CODE = "pub-tgpush-a7d75xtu"


def _load_env() -> None:
    from pathlib import Path
    import os
    f = Path(".env")
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _fetch_channel_bt_ids(settings, date_str: str) -> set[str]:
    from app.radar import RadarClient
    radar = RadarClient(settings.radar_base_url, settings.radar_username, settings.radar_password)
    radar.login()
    bt_tokens = radar.fetch_backtest_tokens(date_str, date_str, page_size=200, max_pages=20)
    ids = {
        t["id"] for t in bt_tokens
        if any(ch["code"] == TARGET_CHANNEL_CODE for ch in (t.get("channels") or []))
    }
    print(f"[flash_scanner] TG频道 backtest_ids: {len(ids)}", flush=True)
    return ids


def run_once(settings, evo_db, date_str: str | None = None) -> None:
    from evolution.db import EvolutionDB
    from evolution.kline import detect_flash_crash

    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    bt_ids = _fetch_channel_bt_ids(settings, date_str)
    if not bt_ids:
        print("[flash_scanner] no backtest_ids for channel, skipping", flush=True)
        return

    pending = evo_db.flash_crash_pending(date_str=date_str, backtest_ids=bt_ids, min_age_hours=1)
    if not pending:
        print("[flash_scanner] no pending cases", flush=True)
        return

    print(f"[flash_scanner] {len(pending)} case(s) to check", flush=True)

    for case in pending:
        pid       = case["push_record_id"]
        chain     = case.get("chain", "")
        address   = case.get("token_address", "")
        push_time = case.get("push_time", "")

        try:
            dt = datetime.fromisoformat(push_time.replace("Z", "+00:00"))
            push_ts = int(dt.timestamp())
        except Exception:
            print(f"[flash_scanner] bad push_time {pid[:8]}: {push_time}", flush=True)
            continue

        print(f"[flash_scanner] checking {chain} {address[:12]} pid={pid[:8]}", flush=True)
        try:
            detected, max_drop, crash_ts = detect_flash_crash(
                settings.gmgn_cli, chain, address, push_ts
            )
            crash_iso = (
                datetime.fromtimestamp(crash_ts, tz=timezone.utc).isoformat()
                if crash_ts else None
            )
            evo_db.update_flash_crash(pid, 1 if detected else 0, max_drop, crash_iso)
            status = "FLASH_CRASH" if detected else "ok"
            print(
                f"[flash_scanner] {chain} {pid[:8]} {status} max_drop={max_drop}",
                flush=True,
            )
        except Exception as e:
            print(f"[flash_scanner] error {pid[:8]}: {e}", flush=True)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _load_env()
    from app.config import load_settings
    from evolution.db import EvolutionDB
    settings = load_settings()
    evo_db = EvolutionDB(settings.db_path)
    evo_db.init_schema()
    run_once(settings, evo_db)
    evo_db.close()


if __name__ == "__main__":
    main()
