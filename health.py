#!/usr/bin/env python3
"""System health check shared by both web dashboards.

Read-only consumer of weather.db. It infers the health of the unattended
pipeline from the data itself — no access to systemd or the sensor needed:

  - local writes (collector): is the newest reading recent? A stale newest row
    means the collector crashed or the sensor dropped off the I2C bus.
  - uploads (pusher): how old is the oldest unpushed row? A backlog older than
    a couple of push cycles means uploads to Supabase are failing.
  - database access: if we can't even read the DB, that's an error in itself.

The fetch (`_fetch_metrics`) is the only side effect — a read-only SQLite
connection. The decision logic (`evaluate`) is pure so it can be unit-tested
with synthetic values and an injected `now`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

# Collector writes every 60s. Allow a little slack before flagging.
WRITE_WARN_SECONDS = 180      # ~3 missed reads
WRITE_ERROR_SECONDS = 600     # 10 min — collector or sensor almost certainly down

# Pusher runs every 300s and drains the whole backlog each cycle, so anything
# older than a few cycles means uploads are actually failing (not normal lag).
UPLOAD_WARN_SECONDS = 900     # 15 min
UPLOAD_ERROR_SECONDS = 3600   # 1 h

_SEVERITY = {"ok": 0, "warn": 1, "error": 2}


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _human(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60} min"
    return f"{s / 3600:.1f} h"


def _fetch_metrics(db_path) -> dict:
    """Read-only snapshot: newest reading + unpushed backlog. Never writes."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        newest = conn.execute(
            "SELECT ts FROM readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        unpushed = conn.execute(
            "SELECT COUNT(*), MIN(ts) FROM readings WHERE pushed = 0"
        ).fetchone()
    finally:
        conn.close()
    return {
        "newest_ts": newest[0] if newest else None,
        "unpushed_count": unpushed[0] if unpushed else 0,
        "oldest_unpushed_ts": unpushed[1] if unpushed else None,
    }


def evaluate(metrics: dict, now: datetime | None = None) -> dict:
    """Pure: turn a metrics snapshot into a health verdict."""
    now = now or datetime.now(timezone.utc)
    checks: dict = {}
    issues: list[str] = []

    # --- local writes (collector) ---
    newest_ts = metrics.get("newest_ts")
    if newest_ts is None:
        checks["local_writes"] = {"status": "error", "detail": "no readings in database"}
        issues.append("No sensor readings recorded yet")
    else:
        age = (now - _parse(newest_ts)).total_seconds()
        if age >= WRITE_ERROR_SECONDS:
            status = "error"
            issues.append(f"No new readings for {_human(age)} — collector or sensor may be down")
        elif age >= WRITE_WARN_SECONDS:
            status = "warn"
            issues.append(f"Last reading was {_human(age)} ago")
        else:
            status = "ok"
        checks["local_writes"] = {
            "status": status, "age_seconds": int(age), "newest_ts": newest_ts
        }

    # --- uploads (pusher) ---
    count = metrics.get("unpushed_count", 0)
    oldest = metrics.get("oldest_unpushed_ts")
    if not count or oldest is None:
        checks["uploads"] = {"status": "ok", "unpushed_count": count}
    else:
        age = (now - _parse(oldest)).total_seconds()
        if age >= UPLOAD_ERROR_SECONDS:
            status = "error"
            issues.append(f"{count} readings not uploaded (oldest {_human(age)} ago) — Supabase uploads failing")
        elif age >= UPLOAD_WARN_SECONDS:
            status = "warn"
            issues.append(f"{count} readings queued for upload (oldest {_human(age)} ago)")
        else:
            status = "ok"
        checks["uploads"] = {
            "status": status, "unpushed_count": count, "oldest_age_seconds": int(age)
        }

    overall = max((c["status"] for c in checks.values()), key=lambda s: _SEVERITY[s])
    return {"status": overall, "issues": issues, "checks": checks}


def check_health(db_path, now: datetime | None = None) -> dict:
    """Top-level entry: fetch + evaluate, with DB errors surfaced as 'error'."""
    try:
        metrics = _fetch_metrics(db_path)
    except Exception as exc:  # locked, missing, corrupt, etc.
        return {
            "status": "error",
            "issues": [f"Cannot read local database ({exc.__class__.__name__})"],
            "checks": {"database": {"status": "error", "detail": str(exc)}},
        }
    return evaluate(metrics, now=now)
