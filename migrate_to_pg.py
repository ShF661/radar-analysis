"""
一次性迁移脚本：把 radar.db (SQLite) 的历史数据导入 Neon PostgreSQL。

用法:
  python migrate_to_pg.py
"""
import sqlite3
import psycopg2
import psycopg2.extras
import os, sys

DB_PATH = "./radar.db"
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    # 从 .env 读取
    for line in open(".env", encoding="utf-8"):
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            DATABASE_URL = line.split("=", 1)[1].strip()
            break

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

print(f"Source: {DB_PATH}")
print(f"Target: {DATABASE_URL[:50]}...")

src = sqlite3.connect(DB_PATH)
src.row_factory = sqlite3.Row
dst = psycopg2.connect(DATABASE_URL)
dst.autocommit = False

def migrate_tokens():
    rows = src.execute("SELECT * FROM tokens").fetchall()
    if not rows:
        print("tokens: no rows")
        return
    cols = [d[0] for d in src.execute("SELECT * FROM tokens LIMIT 0").description]
    cur = dst.cursor()
    col_str = ", ".join(f'"{c}"' for c in cols)
    ph_str  = ", ".join("%s" for _ in cols)
    update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "task_id")
    sql = (
        f'INSERT INTO tokens ({col_str}) VALUES ({ph_str}) '
        f'ON CONFLICT (task_id) DO UPDATE SET {update_set}'
    )
    batch, total = [], 0
    for r in rows:
        batch.append(tuple(r))
        if len(batch) >= 200:
            psycopg2.extras.execute_batch(cur, sql, batch)
            dst.commit()
            total += len(batch)
            print(f"  tokens: {total}/{len(rows)} inserted")
            batch = []
    if batch:
        psycopg2.extras.execute_batch(cur, sql, batch)
        dst.commit()
        total += len(batch)
    print(f"tokens: done ({total} rows)")

def migrate_evolution_cases():
    try:
        rows = src.execute("SELECT * FROM evolution_cases").fetchall()
    except Exception as e:
        print(f"evolution_cases: skip ({e})")
        return
    if not rows:
        print("evolution_cases: no rows")
        return
    cols = [d[0] for d in src.execute("SELECT * FROM evolution_cases LIMIT 0").description]
    # Remove SQLite auto-increment id — PG will generate its own
    data_cols = [c for c in cols if c != "id"]
    cur = dst.cursor()
    col_str = ", ".join(f'"{c}"' for c in data_cols)
    ph_str  = ", ".join("%s" for _ in data_cols)
    sql = (
        f'INSERT INTO evolution_cases ({col_str}) VALUES ({ph_str}) '
        f'ON CONFLICT (push_record_id) DO NOTHING'
    )
    batch, total = [], 0
    idx = {c: i for i, c in enumerate(cols)}
    for r in rows:
        r = tuple(r)
        batch.append(tuple(r[idx[c]] for c in data_cols))
        if len(batch) >= 200:
            psycopg2.extras.execute_batch(cur, sql, batch)
            dst.commit()
            total += len(batch)
            print(f"  evolution_cases: {total}/{len(rows)} inserted")
            batch = []
    if batch:
        psycopg2.extras.execute_batch(cur, sql, batch)
        dst.commit()
        total += len(batch)
    print(f"evolution_cases: done ({total} rows)")

def migrate_prompt_test_results():
    try:
        rows = src.execute("SELECT * FROM prompt_test_results").fetchall()
    except Exception as e:
        print(f"prompt_test_results: skip ({e})")
        return
    if not rows:
        print("prompt_test_results: no rows")
        return
    cols = [d[0] for d in src.execute("SELECT * FROM prompt_test_results LIMIT 0").description]
    data_cols = [c for c in cols if c != "id"]
    cur = dst.cursor()
    col_str = ", ".join(f'"{c}"' for c in data_cols)
    ph_str  = ", ".join("%s" for _ in data_cols)
    sql = f'INSERT INTO prompt_test_results ({col_str}) VALUES ({ph_str})'
    idx = {c: i for i, c in enumerate(cols)}
    batch = [tuple(tuple(r)[idx[c]] for c in data_cols) for r in rows]
    psycopg2.extras.execute_batch(cur, sql, batch)
    dst.commit()
    print(f"prompt_test_results: done ({len(batch)} rows)")

# First init schema on PG side
print("\nInitializing PG schema...")
from app.db_pg import Database as PgDb
from evolution.db_pg import EvolutionDB as PgEvo
PgDb(DATABASE_URL).init_schema()
PgEvo(DATABASE_URL).init_schema()
print("Schema OK")

print("\nMigrating data...")
migrate_tokens()
migrate_evolution_cases()
migrate_prompt_test_results()

src.close()
dst.close()
print("\nDone!")
