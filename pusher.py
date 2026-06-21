#!/usr/bin/env python3
"""Sync unpushed SQLite rows to Supabase every 5 minutes, with auto-replay on reconnect."""

import sqlite3
import time
import logging
import os
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent / "weather.db"
INTERVAL_SECONDS = 300
BATCH_SIZE = 500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def get_config() -> tuple[str, dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/").removesuffix("/rest/v1")
    key = os.environ["SUPABASE_KEY"]
    endpoint = f"{url}/rest/v1/readings"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    return endpoint, headers


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


def push_batch(endpoint: str, headers: dict, rows: list[dict]) -> None:
    payload = [
        {"ts": r["ts"], "temperature_c": r["temperature_c"], "pressure_hpa": r["pressure_hpa"]}
        for r in rows
    ]
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()


def sync_once(conn: sqlite3.Connection, endpoint: str, headers: dict) -> int:
    rows = fetch_unpushed(conn)
    if not rows:
        return 0
    push_batch(endpoint, headers, rows)
    ids = [r["id"] for r in rows]
    mark_pushed(conn, ids)
    return len(rows)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    endpoint, headers = get_config()
    log.info("Pusher started — syncing %s to %s every %ds", DB_PATH, endpoint, INTERVAL_SECONDS)

    while True:
        try:
            total = 0
            while True:
                pushed = sync_once(conn, endpoint, headers)
                if not pushed:
                    break
                total += pushed
            if total:
                log.info("Pushed %d row(s) to Supabase", total)
        except Exception:
            log.exception("Sync failed — will retry next interval")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
