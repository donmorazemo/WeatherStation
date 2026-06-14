#!/usr/bin/env python3
"""Pressure-trend forecast dashboard — independent service on port 5001.

Read-only consumer of the existing weather.db. Does NOT touch the schema,
the collector, the pusher, or the existing webapp. SQLite is opened in WAL
mode by the collector, so concurrent reads here are safe.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import forecast as fc

DB_PATH = Path(__file__).parent / "weather.db"

app = Flask(__name__)


def _connect() -> sqlite3.Connection:
    # uri=True + mode=ro guarantees we never write to the DB.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _fetch_window(hours: float) -> list[tuple[str, float]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT ts, pressure_hpa FROM readings WHERE ts >= ? "
            "ORDER BY ts ASC LIMIT 200000",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], float(r[1])) for r in rows]


def _fetch_baseline(days: int) -> float | None:
    """7-day mean pressure for the anomaly. Single SQL AVG, no bucketing."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT AVG(pressure_hpa), COUNT(*) FROM readings WHERE ts >= ?",
            (cutoff,),
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None or row[1] < 100:
        return None  # not enough samples to call it a baseline
    return float(row[0])


@app.route("/")
def index():
    return render_template(
        "forecast.html",
        history_hours=fc.HISTORY_HOURS,
        bucket_minutes=fc.BUCKET_MINUTES,
        horizon_hours=fc.FORECAST_HORIZON_HOURS,
    )


@app.route("/api/series")
def api_series():
    hours = int(request.args.get("hours", fc.HISTORY_HOURS))
    hours = max(1, min(hours, 24 * 14))  # clamp 1h .. 14 days
    raw = _fetch_window(hours)
    buckets = fc.bucketize(raw)
    return jsonify({
        "hours": hours,
        "bucket_minutes": fc.BUCKET_MINUTES,
        "points": [
            {"ts": b.ts.isoformat(timespec="seconds"), "pressure_hpa": round(b.pressure_hpa, 2)}
            for b in buckets
        ],
    })


@app.route("/api/forecast")
def api_forecast():
    # We need at least 6 h for the confirm trend; the display still uses
    # HISTORY_HOURS via /api/series.
    raw = _fetch_window(max(fc.HISTORY_HOURS, fc.CONFIRM_HOURS * 2))
    buckets = fc.bucketize(raw)
    baseline = _fetch_baseline(fc.BASELINE_DAYS)
    f = fc.forecast(buckets, baseline_hpa=baseline)
    return jsonify({
        "headline": f.headline,
        "detail": f.detail,
        "current_hpa": round(f.current_hpa, 2) if f.current_hpa is not None else None,
        "trend_1h_hpa": round(f.trend_1h_hpa, 2) if f.trend_1h_hpa is not None else None,
        "trend_3h_hpa": round(f.trend_3h_hpa, 2) if f.trend_3h_hpa is not None else None,
        "trend_6h_hpa": round(f.trend_6h_hpa, 2) if f.trend_6h_hpa is not None else None,
        "confirmed": f.confirmed,
        "baseline_hpa": f.baseline_hpa,
        "anomaly_hpa": f.anomaly_hpa,
        "baseline_days": fc.BASELINE_DAYS,
        "horizon_hours": f.horizon_hours,
        "history_hours": fc.HISTORY_HOURS,
        "sample_count": f.sample_count,
        "data_span_hours": f.data_span_hours,
        "trend_coverage_pct": f.trend_coverage_pct,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
