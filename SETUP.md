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
```l

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
5. Open `supabase_schema.sql` from the repo — **not** `schema.sql` (that one is SQLite-only and will error in Supabase). Paste its contents and click **Run**. This creates the `readings` table.
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

### 9.1 Create a Grafana Cloud account

1. Go to [grafana.com](https://grafana.com) and click **Create free account**.
2. Sign up with your email or a Google/GitHub account.
3. After signing in, Grafana will prompt you to **Create a stack**. Give it a name (e.g. `weatherstation`) and choose the region closest to you.
4. Click **Finish setup**. Your Grafana instance URL will be something like `https://yourname.grafana.net`.

---

### 9.2 Find your Supabase database connection details

You need these before configuring Grafana.

1. In Supabase, click the **gear icon (Settings)** in the left sidebar → **Database**.
2. Scroll to **Connection parameters** and note down:
   - **Host**: looks like `db.xxxxxxxxxxxx.supabase.co`
   - **Port**: `5432`
   - **Database name**: `postgres`
   - **User**: `postgres`
   - **Password**: the password you chose when creating the Supabase project in Step 4

> **Tip:** You can also find a ready-made connection string under **Connection string → URI** — it has all the values in one place.

---

### 9.3 Add PostgreSQL as a data source

1. In your Grafana instance, click the **hamburger menu (☰)** in the top-left → **Connections → Data sources**.
2. Click **Add new data source**.
3. Search for **PostgreSQL** and click it.
4. Fill in the fields:

   | Field | Value |
   |-------|-------|
   | **Name** | `Supabase` (or any name you like) |
   | **Host URL** | `db.xxxxxxxxxxxx.supabase.co:5432` |
   | **Database name** | `postgres` |
   | **Username** | `postgres` |
   | **Password** | your Supabase database password |
   | **TLS/SSL Mode** | `require` |
   | **PostgreSQL version** | `15` |

5. Leave everything else as default.
6. Scroll to the bottom and click **Save & test**.
7. You should see a green banner: **"Database Connection OK"**. If you see an error, double-check the host (no `https://`, no trailing slash) and password.

---

### 9.4 Create a dashboard

1. Click **☰ → Dashboards → New → New dashboard**.
2. Click **Add visualization**.
3. In the data source dropdown at the top, select **Supabase** (the one you just added).
4. At the bottom of the screen, switch the query editor from **Builder** to **Code** mode (toggle in the top-right of the query panel).

**Temperature panel** — paste this query:

```sql
SELECT
  ts AS time,
  temperature_c AS "Temperature (°C)"
FROM readings
WHERE ts > NOW() - INTERVAL '24 hours'
ORDER BY ts;
```

5. Set **Panel type** to **Time series** (top-right dropdown).
6. Under **Panel options** on the right, set the title to `Temperature`.
7. Click **Apply** (top-right).

**Add a second panel for pressure:**

8. Back on the dashboard, click **Add → Visualization**.
9. Select the **Supabase** data source again, switch to **Code** mode, and paste:

```sql
SELECT
  ts AS time,
  pressure_hpa AS "Pressure (hPa)"
FROM readings
WHERE ts > NOW() - INTERVAL '24 hours'
ORDER BY ts;
```

10. Set the title to `Pressure` and click **Apply**.

11. Click the **Save** icon (top-right), give the dashboard a name (e.g. `WeatherStation`), and click **Save**.

---

### 9.5 Make the dashboard public (optional)

If you want a shareable link anyone can view without a Grafana login:

1. Open the dashboard, click the **Share** icon (top-right) → **Public dashboard**.
2. Toggle **Enable public access** → **Save**.
3. Copy the public URL — this is the link you can share or bookmark.

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
