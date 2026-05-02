#!/usr/bin/env python3
"""Sync unpushed SQLite rows to Supabase every 5 minutes, with auto-replay on reconnect."""

import sqlite3
import time
import logging
import os
from pathlib import Path

from supabase import create_client, Client

DB_PATH = Path(__file__).parent / "weather.db"
INTERVAL_SECONDS = 300
BATCH_SIZE = 500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def get_supabase_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def fetch_unpushed(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, temperature_c, pressure_hpa FROM readings WHERE pushed = 0 LIMIT ?",
        (BATCH_SIZE,),
    ).fetchall()
    return [
        {"id": r[0], "ts": r[1], "temperature_c": r[2], "pressure_hpa": r[3]}
        for r in rows
    ]


def mark_pushed(conn: sqlite3.Connection, ids: list[int]) -> None:
    conn.execute(
        f"UPDATE readings SET pushed = 1 WHERE id IN ({','.join('?' * len(ids))})",
        ids,
    )
    conn.commit()


def push_batch(supabase: Client, rows: list[dict]) -> None:
    payload = [
        {"ts": r["ts"], "temperature_c": r["temperature_c"], "pressure_hpa": r["pressure_hpa"]}
        for r in rows
    ]
    supabase.table("readings").insert(payload).execute()


def sync_once(conn: sqlite3.Connection, supabase: Client) -> int:
    rows = fetch_unpushed(conn)
    if not rows:
        return 0
    push_batch(supabase, rows)
    ids = [r["id"] for r in rows]
    mark_pushed(conn, ids)
    return len(rows)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    supabase = get_supabase_client()
    log.info("Pusher started — syncing %s to Supabase every %ds", DB_PATH, INTERVAL_SECONDS)

    while True:
        try:
            pushed = sync_once(conn, supabase)
            if pushed:
                log.info("Pushed %d row(s) to Supabase", pushed)
        except Exception:
            log.exception("Sync failed — will retry next interval")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
