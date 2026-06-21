# WeatherStation

12-month continuous weather monitoring on a Raspberry Pi 2 with BMP280 sensor, SQLite buffering, Supabase cloud sync, and Grafana dashboard.

## Architecture

```
Pi (collector.py)  →  SQLite (WAL)  →  pusher.py  →  Supabase PostgreSQL  →  Grafana Cloud
                            ↓
                    Google Drive (rclone daily backup)
```

## Hardware

| Part | ~Cost |
|------|-------|
| Raspberry Pi 2 | $10 |
| BMP280 sensor | $4 |
| DS3231 RTC module | $4 |
| High-endurance SD card (32 GB) | $10 |
| USB WiFi adapter | $5 |
| **Total** | **~$33** |

## Quick Start

### 1. Clone on the Pi

```bash
git clone https://github.com/donmorazemo/WeatherStation.git
cd WeatherStation
cp .env.example .env
# Edit .env with your Supabase URL and key
```

### 2. Create Supabase table

Paste `supabase_schema.sql` into the Supabase SQL editor and run it.

### 3. Run setup

```bash
chmod +x setup.sh
./setup.sh
```

This installs dependencies, enables I2C, initialises the local SQLite database, and registers + starts both systemd services.

## Services

| Service | What it does | Interval |
|---------|-------------|----------|
| `collector.py` | Reads BMP280 → SQLite; drives the fan plug | Every 60 s (plug check every 5 s) |
| `pusher.py` | SQLite → Supabase (unpushed rows) | Every 5 min |
| `webapp.py` | Live dashboard on `:5000` (temp + fan control + health) | — |
| `forecast_app.py` | Pressure forecast dashboard on `:5001` | Refresh every 60 s |

All services restart automatically on failure. Unpushed rows replay on reconnect,
and the pusher drains the **entire** backlog in one cycle once connectivity returns
(e.g. after a Supabase pause), instead of one 500-row batch per interval.

## Fan Control

The collector switches a Feit/Tuya smart plug (a fan) based on temperature. The
`:5000` dashboard exposes a three-way control written to `FAN_MODE` in `.env`:

| Mode | Behaviour |
|------|-----------|
| **Auto** | Plug follows temperature vs. the threshold (`TEMP_THRESHOLD_C`) |
| **On** | Plug forced on, regardless of temperature |
| **Off** | Plug forced off, regardless of temperature |

The collector re-reads `FAN_MODE` every 5 s (no restart needed). Manual On/Off work
even if the sensor is offline. Endpoints: `GET`/`POST /api/fan-mode`, `GET`/`POST /api/threshold`.

## System Health

Both dashboards show a status LED (top-right) backed by `health.py`, a read-only
module that infers the health of the whole pipeline from `weather.db` alone. It is
served at `GET /api/health` on both `:5000` and `:5001`. The LED is green / amber /
red for the **worst** of four checks, and a panel lists every active issue:

| Check | Flags | Detects |
|-------|-------|---------|
| Local writes | newest row > 3 min (amber) / > 10 min (red) | collector crashed or sensor off the I2C bus |
| Uploads | oldest unpushed row > 15 min (amber) / > 1 h (red) | pusher / Supabase uploads failing |
| Sensor frozen | identical temp **and** pressure ≥ 10 samples over ≥ 15 min (red) | a stuck sensor that is *still writing* (the write check alone misses this) |
| Sensor glitch | ≥ 8 °C or ≥ 12 hPa jump between readings < 3 min apart (amber) | an implausible single-reading spike |
| Database | unreadable / locked / missing (red) | local DB problem |

Thresholds are constants at the top of `health.py`. Covered by `tests/test_health.py`.

## Pressure Forecast (`forecast_app.py`)

A separate Flask service on **port 5001** that reads `weather.db` **read-only** and
shows the last 72 hours of barometric pressure plus a plain-English forecast for
the next 12 hours. It does not touch the collector, the pusher, or the schema.

**How it forecasts (plain English).** Barometric pressure is the single best
indicator a home weather station has. The 3-hour pressure *trend* is what
matters — not the absolute value:

| Δ over 3 h | What it usually means |
|---|---|
| > +6 hPa | Clearing rapidly, possibly cooler/windier |
| +1.5 to +6 hPa | Fair weather improving |
| ±1.5 hPa | Steady — no significant change |
| −1.5 to −6 hPa | Clouds and rain likely within 12–24 h |
| < −6 hPa | Storm likely within hours |

This is the same "Zambretti-style" approach used by Davis, Acurite, and most
consumer weather stations. Pressure alone is reliable out to roughly 12–24 h;
beyond that you need wind, humidity, satellite data, etc.

**Parameters used (from standard meteorological practice):**

- **History window (N) — 72 hours / 3 days.** Standard consumer weather-station
  window: enough context to spot fronts moving in, not so much that the chart
  gets noisy.
- **Sample/aggregation interval (X) — 10 minutes.** Raw 1-minute sensor
  readings are averaged into 10-minute buckets. Smooths out sensor jitter while
  keeping the 3-hour slope sharp.
- **Forecast horizon (Y) — 12 hours.** The classic Zambretti window. Pressure
  trends just don't carry useful signal further out than that.
- **Trend window — 3 hours.** Standard barograph slope window; long enough to
  ignore short bumps, short enough to react to incoming fronts.
- **Confirm window — 6 hours.** A second regression slope used to confirm the
  3-hour verdict. If they don't agree (different sign, or 6 h magnitude under
  1 hPa), the page shows `Watch — not yet confirmed` instead of a confident
  rain/fair call. This filters the semi-diurnal atmospheric pressure tide
  (~1 hPa twice a day) and short HVAC events.
- **Baseline window — 7 days.** Rolling mean pressure used to compute the
  *anomaly* (current − baseline). Tells you whether you're sitting in a high
  or a low relative to the recent regime — context the trend alone can't give.

Endpoints:
- `GET /` — dashboard
- `GET /api/series?hours=72` — bucketed pressure JSON
- `GET /api/forecast` — current verdict, trends, sample count

## Database

`schema.sql` — local SQLite (WAL mode, survives power cuts)  
`supabase_schema.sql` — remote Postgres table

CHECK constraints reject out-of-range readings at the database level:
- Temperature: −40 °C to 85 °C
- Pressure: 300 hPa to 1100 hPa

## Grafana Dashboard

Connect Grafana Cloud to Supabase via the PostgreSQL data source, then use queries like:

```sql
-- Last 24 hours temperature
SELECT ts AS time, temperature_c AS "Temperature (°C)"
FROM readings
WHERE ts > NOW() - INTERVAL '24 hours'
ORDER BY ts;
```

## Backups

Install rclone and add a daily cron job:

```bash
0 2 * * * rclone copy /home/pi/WeatherStation/weather.db gdrive:weather-backups/
```

## Capacity

~40 MB/year growth — well within Supabase's 500 MB free tier (~5 years headroom).
