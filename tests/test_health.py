"""Tests for health.py.

Covers:
- Pure `evaluate` verdicts for local writes (collector) and uploads (pusher)
  across the ok / warn / error thresholds.
- Overall status is the worst of the individual checks.
- Empty database is an error.
- `check_health` surfaces an unreadable DB as an error instead of raising.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make `health` importable when running pytest from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import health  # noqa: E402

NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)


def _ago(seconds: int) -> str:
    return (NOW - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _metrics(write_age=30, unpushed=0, oldest_age=None):
    return {
        "newest_ts": _ago(write_age),
        "unpushed_count": unpushed,
        "oldest_unpushed_ts": _ago(oldest_age) if oldest_age is not None else None,
    }


# --- local writes ---------------------------------------------------------

def test_fresh_writes_ok():
    h = health.evaluate(_metrics(write_age=30), now=NOW)
    assert h["checks"]["local_writes"]["status"] == "ok"
    assert h["status"] == "ok"
    assert h["issues"] == []


def test_slightly_stale_writes_warn():
    h = health.evaluate(_metrics(write_age=200), now=NOW)
    assert h["checks"]["local_writes"]["status"] == "warn"
    assert h["status"] == "warn"
    assert any("Last reading" in i for i in h["issues"])


def test_very_stale_writes_error():
    h = health.evaluate(_metrics(write_age=1200), now=NOW)
    assert h["checks"]["local_writes"]["status"] == "error"
    assert h["status"] == "error"
    assert any("collector or sensor" in i for i in h["issues"])


def test_empty_db_is_error():
    h = health.evaluate({"newest_ts": None, "unpushed_count": 0, "oldest_unpushed_ts": None}, now=NOW)
    assert h["status"] == "error"
    assert h["checks"]["local_writes"]["status"] == "error"


# --- uploads --------------------------------------------------------------

def test_small_recent_backlog_ok():
    # A couple of rows waiting for the next 5-min push cycle is normal.
    h = health.evaluate(_metrics(unpushed=3, oldest_age=120), now=NOW)
    assert h["checks"]["uploads"]["status"] == "ok"
    assert h["status"] == "ok"


def test_aging_backlog_warn():
    h = health.evaluate(_metrics(unpushed=200, oldest_age=1000), now=NOW)
    assert h["checks"]["uploads"]["status"] == "warn"
    assert h["status"] == "warn"


def test_old_backlog_error():
    h = health.evaluate(_metrics(unpushed=3500, oldest_age=7200), now=NOW)
    assert h["checks"]["uploads"]["status"] == "error"
    assert h["status"] == "error"
    assert any("uploads failing" in i.lower() for i in h["issues"])


# --- combination & overall ------------------------------------------------

def test_overall_is_worst_check():
    # Writes fine, uploads failing -> overall error.
    h = health.evaluate(_metrics(write_age=30, unpushed=3500, oldest_age=7200), now=NOW)
    assert h["checks"]["local_writes"]["status"] == "ok"
    assert h["checks"]["uploads"]["status"] == "error"
    assert h["status"] == "error"


def test_check_health_unreadable_db_is_error():
    h = health.check_health("/nonexistent/path/weather.db", now=NOW)
    assert h["status"] == "error"
    assert "database" in h["checks"]
