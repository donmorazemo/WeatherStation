#!/usr/bin/env python3
"""Web dashboard — current temperature, pressure, and threshold control."""

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv, set_key
from flask import Flask, jsonify, render_template, request

ENV_PATH = Path(__file__).parent / ".env"
DB_PATH = Path(__file__).parent / "weather.db"

app = Flask(__name__)


def latest_reading() -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT ts, temperature_c, pressure_hpa FROM readings ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"ts": row[0], "temperature_c": row[1], "pressure_hpa": row[2]}


def current_threshold() -> float:
    load_dotenv(ENV_PATH, override=True)
    return float(os.getenv("TEMP_THRESHOLD_C", "25.5"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/current")
def api_current():
    reading = latest_reading()
    if not reading:
        return jsonify({"error": "no data"}), 404
    threshold = current_threshold()
    reading["threshold_c"] = threshold
    reading["fan_on"] = reading["temperature_c"] > threshold
    return jsonify(reading)


@app.route("/api/threshold", methods=["GET"])
def api_get_threshold():
    return jsonify({"threshold_c": current_threshold()})


@app.route("/api/threshold", methods=["POST"])
def api_set_threshold():
    data = request.get_json()
    try:
        value = round(float(data["threshold_c"]), 1)
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "invalid value"}), 400
    set_key(str(ENV_PATH), "TEMP_THRESHOLD_C", str(value))
    return jsonify({"threshold_c": value})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
