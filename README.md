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
| `collector.py` | Reads BMP280 → SQLite | Every 60 s |
| `pusher.py` | SQLite → Supabase (unpushed rows) | Every 5 min |

Both services restart automatically on failure. Unpushed rows replay on reconnect.

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
