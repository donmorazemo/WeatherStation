#!/usr/bin/env python3
"""System health check shared by both web dashboards.

Read-only consumer of weather.db. It infers the health of the unattended
pipeline from the data itself — no access to systemd or the sensor needed:

  - local writes (collector): is the newest reading recent? A stale newest row
    means the collector crashed or the sensor dropped off the I2C bus.
  - uploads (pusher): how old is the oldest unpushed row? A backlog older than
    a couple of push cycles means uploads to Supabase are failing.
  - sensor plausibility: are the readings themselves believable? A live BMP280
    always jitters at 0.01 resolution, so identical temp AND pressure across a
    long stretch means the sensor is frozen/stuck (the collector keeps writing,
    so the "local writes" check alone would miss this). Also flags an
    implausible jump between two readings taken close together (a glitch).
  - database access: if we can't even read the DB, that's an error in itself.

The fetch (`_fetch_metrics`) is the only side effect — a read-only SQLite
connection. The decision logic (`evaluate`) is pure so it can be unit-tested
with synthetic values and an injected `now`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

# Collector writes every 60s. Allow a little slack before flagging.
WRITE_WARN_SECONDS = 180      # ~3 missed reads
WRITE_ERROR_SECONDS = 600     # 10 min — collector or sensor almost certainly down

# Pusher runs every 300s and drains the whole backlog each cycle, so anything
# older than a few cycles means uploads are actually failing (not normal lag).
UPLOAD_WARN_SECONDS = 900     # 15 min
UPLOAD_ERROR_SECONDS = 3600   # 1 h

# Stuck sensor: a working BMP280 jitters every reading at 0.01 resolution.
# Identical temperature AND pressure across a long, well-sampled stretch is the
# signature of a frozen sensor. Require both a minimum sample count and a real
# time span so a couple of rapid identical reads can't trip it.
STUCK_WINDOW_SECONDS = 1200     # look back 20 min
STUCK_MIN_SAMPLES = 10
STUCK_MIN_SPAN_SECONDS = 900    # ...spanning at least 15 min

# Implausible jump between two readings taken close together => sensor glitch.
# Only compares near-adjacent reads so a legitimate gap (collector was down) is
# never mistaken for a jump. Thresholds are deliberately generous — these are
# physically impossible indoors over ~1 minute, not merely unusual.
JUMP_MAX_GAP_SECONDS = 180
TEMP_JUMP_C = 8.0
PRESSURE_JUMP_HPA = 12.0

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
    """Read-only snapshot: newest reading, unpushed backlog, recent values."""
    recent_cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=STUCK_WINDOW_SECONDS)
    ).isoformat(timespec="seconds")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        newest = conn.execute(
            "SELECT ts FROM readings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        unpushed = conn.execute(
            "SELECT COUNT(*), MIN(ts) FROM readings WHERE pushed = 0"
        ).fetchone()
        recent = conn.execute(
            "SELECT ts, temperature_c, pressure_hpa FROM readings "
            "WHERE ts >= ? ORDER BY ts ASC LIMIT 5000",
            (recent_cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "newest_ts": newest[0] if newest else None,
        "unpushed_count": unpushed[0] if unpushed else 0,
        "oldest_unpushed_ts": unpushed[1] if unpushed else None,
        "recent": [(r[0], r[1], r[2]) for r in recent],
    }


def _find_jump(recent: list) -> str | None:
    """Return a message for the first implausible jump between near-adjacent
    readings, or None. Pairs more than JUMP_MAX_GAP_SECONDS apart are skipped."""
    for (ts0, t0, p0), (ts1, t1, p1) in zip(recent, recent[1:]):
        gap = (_parse(ts1) - _parse(ts0)).total_seconds()
        if gap <= 0 or gap > JUMP_MAX_GAP_SECONDS:
            continue
        if abs(float(t1) - float(t0)) >= TEMP_JUMP_C:
            return (f"Implausible temperature jump of {abs(float(t1) - float(t0)):.1f}°C "
                    "between consecutive readings — possible sensor glitch")
        if abs(float(p1) - float(p0)) >= PRESSURE_JUMP_HPA:
            return (f"Implausible pressure jump of {abs(float(p1) - float(p0)):.1f} hPa "
                    "between consecutive readings — possible sensor glitch")
    return None


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

    # --- sensor plausibility (frozen / glitch) ---
    recent = metrics.get("recent") or []
    sensor = {"status": "ok", "samples": len(recent)}
    if len(recent) >= 2:
        temps = {round(float(r[1]), 2) for r in recent}
        pressures = {round(float(r[2]), 2) for r in recent}
        span = (_parse(recent[-1][0]) - _parse(recent[0][0])).total_seconds()
        sensor["distinct_temp"] = len(temps)
        sensor["distinct_pressure"] = len(pressures)
        frozen = (
            len(recent) >= STUCK_MIN_SAMPLES
            and span >= STUCK_MIN_SPAN_SECONDS
            and len(temps) == 1
            and len(pressures) == 1
        )
        if frozen:
            sensor["status"] = "error"
            issues.append(
                f"Sensor frozen — identical temperature & pressure for {_human(span)}; "
                "sensor may be stuck"
            )
        else:
            jump = _find_jump(recent)
            if jump:
                sensor["status"] = "warn"
                issues.append(jump)
    checks["sensor"] = sensor

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
