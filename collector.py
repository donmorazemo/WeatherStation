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
        return None
    return tinytuya.OutletDevice(dev_id=device_id, address=ip, local_key=local_key, version=3.3)


def get_threshold() -> float:
    load_dotenv(Path(__file__).parent / ".env", override=True)
    return float(os.getenv("TEMP_THRESHOLD_C", "25.5"))


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

    plug_device = load_plug_config()
    if plug_device:
        log.info("Plug control enabled — threshold %.1f°C", get_threshold())
    else:
        log.info("Plug control disabled — set PLUG_DEVICE_ID, PLUG_LOCAL_IP, PLUG_LOCAL_KEY in .env to enable")

    log.info("Collector started — writing to %s", DB_PATH)

    last_temp: float | None = None
    last_plug_state: bool | None = None
    CHECK_INTERVAL = 5
    ticks_per_read = INTERVAL_SECONDS // CHECK_INTERVAL

    tick = 0
    while True:
        if tick % ticks_per_read == 0:
            try:
                ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                last_temp, pressure_hpa = read_sensor(bmp)
                insert_reading(conn, ts, last_temp, pressure_hpa)
                log.info("Recorded %s  %.2f°C  %.2f hPa", ts, last_temp, pressure_hpa)
            except Exception:
                log.exception("Failed to read/store sensor data")

        if plug_device and last_temp is not None:
            try:
                threshold = get_threshold()
                should_be_on = last_temp > threshold
                if should_be_on != last_plug_state:
                    control_plug(plug_device, should_be_on)
                    last_plug_state = should_be_on
                    log.info("Plug %s (%.2f°C %s %.1f°C threshold)", "ON" if should_be_on else "OFF", last_temp, ">" if should_be_on else "<=", threshold)
            except Exception:
                log.exception("Failed to check/control plug")

        tick += 1
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
