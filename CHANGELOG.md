# Changelog

All notable changes to this project are documented here.

---

## [2026-06-20]

### Added — Manual Fan Control
- The `:5000` dashboard now has a three-way **Auto / On / Off** fan control. Mode is stored in `.env` as `FAN_MODE` and re-read by the collector every 5 s — no restart needed.
- `On`/`Off` force the plug regardless of temperature and work even when the sensor is offline; `Auto` keeps the existing temperature-vs-threshold logic.
- New endpoints `GET`/`POST /api/fan-mode`; `/api/current` now also returns `fan_mode`.

### Added — System Health Status LED
- New shared `health.py` (read-only, pure-logic + `check_health(db_path)`) infers pipeline health from `weather.db` alone, served at `GET /api/health` on both `:5000` and `:5001`.
- Both dashboards render a green/amber/red status LED (top-right) showing the **worst** of four checks, with a panel listing every active issue (visible on touch screens, not just on hover):
  - **Local writes** — newest reading stale (collector/sensor down).
  - **Uploads** — oldest unpushed row aging (pusher/Supabase failing).
  - **Sensor frozen** — identical temperature *and* pressure across ≥10 samples over ≥15 min while still writing (a stuck sensor the write check alone misses).
  - **Sensor glitch** — physically impossible jump (≥8 °C or ≥12 hPa) between near-adjacent readings.
  - **Database** — unreadable/locked/missing DB.
- Tests: new `tests/test_health.py` (15 cases; 46 total).

### Changed — Dashboard Layout
- Pressure moved from a prominent card to a small muted line; temperature is now the single headline reading on the fan-control page.

### Changed — Pusher Backlog Drain
- The pusher now drains the **entire** unpushed backlog in one cycle (looping 500-row batches until empty) instead of one batch per 5-minute interval. A large backlog after a Supabase pause now clears in a single pass. Replay-on-reconnect semantics unchanged.

---

## [2026-06-13b]

### Added — 6 h Confirm Trend + 7-Day Anomaly
- Added a second 6-hour regression slope (`trend_6h_hpa`) used to *confirm* the primary 3 h verdict. Filters the most common false positive — the semi-diurnal atmospheric pressure tide (~1 hPa rise/fall twice a day) and short HVAC bumps that look like a real front over 3 h but don't sustain over 6 h.
- When the 3 h trend is non-steady but the 6 h trend doesn't back it up (different sign or magnitude < 1 hPa), the verdict is downgraded to `Watch — possible front/clearing, not yet confirmed` rather than confidently predicting rain or fair weather. UI shows a `Confirmed` / `Unconfirmed` badge next to the headline.
- Added a 7-day rolling baseline (`baseline_hpa`) and anomaly (`anomaly_hpa = current − baseline`), surfaced on the page as a colored pill under the current reading. Lets you tell whether the current pressure is high or low relative to recent weather, not just where it's trending.
- Tests: +10 new pytest cases (31 total) covering 6 h slope, agreement/downgrade, anomaly math, and a tent-shaped tide pattern that the old version would have falsely called rain.

---

## [2026-06-13]

### Fixed — Forecast Reliability
- Replaced the 3-hour trend computation (endpoint-difference) with a least-squares regression slope across the window. Single ±0.3 hPa sensor jitter no longer swings the verdict.
- Added a coverage gate: the verdict is held back as "Collecting data" unless ≥60% of the 3-hour trend window is populated. Prevents 30 min of readings producing a confident 12-hour forecast.
- `/api/forecast` now returns `data_span_hours` and `trend_coverage_pct`; the page shows both so you can see what data backs the verdict.
- Chart Y-axis padded to a minimum 4 hPa range so calm pressure doesn't visually look like dramatic swings.
- Added `tests/test_forecast.py` (21 pytest cases) covering bucketing, regression vs endpoint behaviour, noise robustness, coverage gating, all verdict branches, edge cases, and realistic indoor noise + HVAC drift.

---

## [2026-06-12]

### Added — Pressure Forecast Service
- New `forecast_app.py` Flask service on port 5001, independent of the existing webapp
- Reads the existing `weather.db` **read-only** (WAL mode) — does not modify collector, pusher, schema, or any running service
- New `forecast.py` — pure functions for 10-minute bucketing, 3-hour pressure trend, and plain-English forecast lookup
- New `templates/forecast.html` — Chart.js line graph of the last 72 hours of pressure plus a forecast card and trend metrics
- New `systemd/forecast.service` — auto-starts on boot, restart on crash
- Forecast parameters chosen from standard meteorological practice:
  - **History window (N):** 72 hours (3 days) shown on the graph
  - **Sample/aggregation interval (X):** 10 minutes (downsampled from existing 1-min readings)
  - **Forecast horizon (Y):** 12 hours
  - **Trend window:** 3 hours (Zambretti-style), altitude-independent

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
