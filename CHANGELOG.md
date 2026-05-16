# Changelog

All notable changes to this project are documented here.

---

## [2026-05-16]

### Fixed — Web Dashboard Timestamps
- "Reading taken" timestamp was showing "Invalid Date" — fixed by correctly parsing the `+00:00` UTC offset from SQLite
- Both timestamps now include the date (e.g. "May 16, 10:01:43 AM PT") in addition to the time
- Added two Pacific Time timestamps to the dashboard: "Reading taken" (when sensor last measured) and "Page refreshed" (updates every 5s — confirms live data even when temperature is unchanged between 60s reads)

---


### Added — Web Dashboard
- New `webapp.py` Flask app running on port 5000, accessible from any device on the home network
- Displays current temperature (°F), pressure, and fan on/off status
- Auto-refreshes every 5 seconds
- Threshold input in °F — changes take effect within 5 seconds, no restart required
- New `systemd/webapp.service` — starts automatically on boot

### Added — Command-Line Threshold Control
- New `set-threshold.sh` script to update fan threshold from the terminal
- Restarts the collector service immediately so the new value takes effect at once

### Added — Feit Smart Plug Control
- Collector now controls a Feit smart plug (Tuya protocol) via `tinytuya` over local WiFi
- Plug turns ON when temperature exceeds threshold, OFF when it drops back below
- Threshold stored in `.env` as `TEMP_THRESHOLD_C` (default 25.5°C / 78°F)
- Plug credentials (`PLUG_DEVICE_ID`, `PLUG_LOCAL_IP`, `PLUG_LOCAL_KEY`) configured in `.env`

### Changed — Collector Loop
- Main loop now ticks every 5 seconds instead of 60
- Sensor read and SQLite insert still happen every 60 seconds (cloud upload frequency unchanged)
- Threshold is re-evaluated every 5 seconds so plug responds quickly to setting changes
- Plug commands only sent when state actually changes (avoids unnecessary network traffic)

### Changed — Username
- Replaced hardcoded `pi` user with `ashishnarain` throughout all systemd service files and docs

### Dependencies Added
- `tinytuya` — local WiFi control of Tuya-compatible smart plugs
- `python-dotenv` — `.env` file loading
- `flask` — web dashboard

---

## [Initial Release]

### Added
- `collector.py` — reads BMP280 sensor every 60 seconds, buffers to local SQLite (`weather.db`)
- `pusher.py` — syncs unpushed rows to Supabase every 5 minutes, replays on reconnect
- `schema.sql` — local SQLite schema with WAL mode for crash safety
- `supabase_schema.sql` — remote PostgreSQL schema for Supabase
- `setup.sh` — installs dependencies, initialises DB, registers systemd services
- `systemd/collector.service` and `systemd/pusher.service` — auto-start on boot, restart on crash
- Grafana Cloud dashboards: real-time (2h), hourly averages (7d), daily highs & lows (30d)
- Google Drive daily backup via rclone cron job
