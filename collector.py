#!/usr/bin/env python3
"""Read BMP280 sensor every 60 seconds and buffer readings to local SQLite."""

import os
import sqlite3
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import board
import adafruit_bmp280
import tinytuya
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DB_PATH = Path(__file__).parent / "weather.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
INTERVAL_SECONDS = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_plug_config():
    device_id = os.getenv("PLUG_DEVICE_ID")
    ip = os.getenv("PLUG_LOCAL_IP")
    local_key = os.getenv("PLUG_LOCAL_KEY")
    if not all([device_id, ip, local_key]):
        return None, None
    device = tinytuya.OutletDevice(dev_id=device_id, address=ip, local_key=local_key, version=3.3)
    threshold = float(os.getenv("TEMP_THRESHOLD_C", "25.5"))
    return device, threshold


def control_plug(device, turn_on: bool) -> None:
    try:
        if turn_on:
            device.turn_on()
        else:
            device.turn_off()
    except Exception:
        log.exception("Failed to control plug")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


def read_sensor(bmp: adafruit_bmp280.Adafruit_BMP280_I2C) -> tuple[float, float]:
    temperature_c = round(bmp.temperature, 2)
    pressure_hpa = round(bmp.pressure, 2)
    return temperature_c, pressure_hpa


def insert_reading(
    conn: sqlite3.Connection, ts: str, temperature_c: float, pressure_hpa: float
) -> None:
    conn.execute(
        "INSERT INTO readings (ts, temperature_c, pressure_hpa) VALUES (?, ?, ?)",
        (ts, temperature_c, pressure_hpa),
    )
    conn.commit()


def main() -> None:
    i2c = board.I2C()
    bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    plug_device, threshold = load_plug_config()
    if plug_device:
        log.info("Plug control enabled — threshold %.1f°C", threshold)
    else:
        log.info("Plug control disabled — set PLUG_DEVICE_ID, PLUG_LOCAL_IP, PLUG_LOCAL_KEY in .env to enable")

    log.info("Collector started — writing to %s", DB_PATH)

    while True:
        try:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            temperature_c, pressure_hpa = read_sensor(bmp)
            insert_reading(conn, ts, temperature_c, pressure_hpa)
            log.info("Recorded %s  %.2f°C  %.2f hPa", ts, temperature_c, pressure_hpa)
            if plug_device:
                should_be_on = temperature_c > threshold
                control_plug(plug_device, should_be_on)
                log.info("Plug %s (%.2f°C %s %.1f°C threshold)", "ON" if should_be_on else "OFF", temperature_c, ">" if should_be_on else "<=", threshold)
        except Exception:
            log.exception("Failed to read/store sensor data")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
