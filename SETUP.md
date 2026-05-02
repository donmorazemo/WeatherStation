# WeatherStation Setup Guide

This guide walks you through setting up the WeatherStation software from scratch. It assumes your Raspberry Pi is powered on, connected to WiFi, and the BMP280 sensor and DS3231 RTC are wired up.

---

## Step 1: Enable I2C on the Pi

The BMP280 and DS3231 both communicate over I2C, which is disabled by default.

```bash
sudo raspi-config
```

Navigate to **Interface Options → I2C → Yes**, then reboot:

```bash
sudo reboot
```

After rebooting, verify the sensors are detected:

```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
```

You should see addresses `0x76` or `0x77` (BMP280) and `0x68` (DS3231) in the output grid.

---

## Step 2: Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git
```

---

## Step 3: Clone the Repository

```bash
cd ~
git clone https://github.com/donmorazemo/WeatherStation.git
cd WeatherStation
```

---

## Step 4: Set Up Supabase

1. Go to [supabase.com](https://supabase.com) and create a free account.
2. Click **New project**, give it a name (e.g. `weatherstation`), set a database password, choose a region close to you.
3. Wait for the project to finish provisioning (~1 min).
4. In the left sidebar, click **SQL Editor**.
5. Paste the contents of `supabase_schema.sql` and click **Run**. This creates the `readings` table.
6. Go to **Project Settings → API**.
7. Copy the **Project URL** and the **anon/public key** — you'll need these in the next step.

---

## Step 5: Configure Environment Variables

```bash
cp .env.example .env
nano .env
```

Fill in your values:

```
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your-anon-public-key
```

Save and exit (`Ctrl+X`, then `Y`, then `Enter`).

---

## Step 6: Run the Setup Script

```bash
chmod +x setup.sh
./setup.sh
```

This will:
- Install Python dependencies (`adafruit-circuitpython-bmp280`, `supabase`)
- Initialise the local SQLite database (`weather.db`)
- Copy and enable the `collector` and `pusher` systemd services
- Start both services immediately

---

## Step 7: Verify the Services Are Running

Check that both services started without errors:

```bash
sudo systemctl status collector
sudo systemctl status pusher
```

Both should show **active (running)**. To watch live logs:

```bash
# Collector (new reading every 60 seconds)
journalctl -u collector -f

# Pusher (sync every 5 minutes)
journalctl -u pusher -f
```

You can also inspect the local database directly:

```bash
sqlite3 weather.db "SELECT * FROM readings ORDER BY id DESC LIMIT 5;"
```

---

## Step 8: Confirm Data Is Reaching Supabase

1. In Supabase, click **Table Editor → readings**.
2. After ~5 minutes you should see rows appearing.

If no rows appear, check the pusher logs (`journalctl -u pusher -f`) for errors.

---

## Step 9: Set Up Grafana Cloud

1. Go to [grafana.com](https://grafana.com) and create a free account.
2. Create a new **Grafana Cloud** stack.
3. In your Grafana instance, go to **Connections → Add new connection → PostgreSQL**.
4. Fill in the connection details from Supabase (**Project Settings → Database**):
   - **Host**: your Supabase DB host (e.g. `db.xxxx.supabase.co:5432`)
   - **Database**: `postgres`
   - **User**: `postgres`
   - **Password**: the database password you set in Step 4
   - **TLS/SSL Mode**: `require`
5. Click **Save & test** — you should see a green "Database Connection OK".
6. Go to **Dashboards → New Dashboard → Add visualization**.
7. Select your PostgreSQL source and use a query like:

```sql
SELECT
  ts AS time,
  temperature_c AS "Temperature (°C)",
  pressure_hpa AS "Pressure (hPa)"
FROM readings
WHERE ts > NOW() - INTERVAL '24 hours'
ORDER BY ts;
```

Set the panel type to **Time series** and save.

---

## Step 10: Set Up Daily Google Drive Backups

Install rclone:

```bash
curl https://rclone.org/install.sh | sudo bash
```

Configure it for Google Drive:

```bash
rclone config
```

Follow the prompts:
- Choose `n` for new remote
- Name it `gdrive`
- Choose `drive` as the storage type
- Follow the OAuth flow in your browser to authorise access

Once configured, test it:

```bash
rclone lsd gdrive:
```

Add a daily cron job to back up the database at 2 AM:

```bash
crontab -e
```

Add this line:

```
0 2 * * * rclone copy /home/pi/WeatherStation/weather.db gdrive:weather-backups/
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `i2cdetect` shows no addresses | Check wiring: SDA→GPIO2, SCL→GPIO3, 3.3V, GND |
| `collector` service fails to start | Run `python3 collector.py` manually to see the error |
| No rows in Supabase after 10 min | Check `.env` values; run `python3 pusher.py` manually |
| `pusher` shows auth errors | Regenerate your Supabase anon key and update `.env` |
| Grafana shows "no data" | Confirm the DB host/password in the data source settings |

---

## What Runs Automatically

Once setup is complete, everything runs without any manual intervention:

- **Every 60 seconds**: temperature and pressure logged to `weather.db`
- **Every 5 minutes**: new readings synced to Supabase
- **On reboot**: both services start automatically via systemd
- **On network drop**: pusher replays any missed rows when connectivity returns
- **Every night at 2 AM**: `weather.db` backed up to Google Drive
