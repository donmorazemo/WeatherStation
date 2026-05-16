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

Fill in your Supabase values:

```
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your-anon-public-key
```

If you are using a Feit smart plug (see Step 5a), also add:

```
PLUG_DEVICE_ID=your_device_id_here
PLUG_LOCAL_IP=192.168.x.x
PLUG_LOCAL_KEY=your_local_key_here
TEMP_THRESHOLD_C=25.5
```

Save and exit (`Ctrl+X`, then `Y`, then `Enter`).

---

## Step 5a: Set Up Feit Smart Plug Control (Optional)

The collector can automatically turn a Feit smart plug ON when temperature exceeds a threshold and OFF when it drops back below. The plug is controlled locally over WiFi — no cloud dependency at runtime.

### Get your plug's credentials

You need three values from your plug: **Device ID**, **Local IP**, and **Local Key**. The easiest way to get them is with the tinytuya wizard.

**1. Create a Tuya IoT Platform account**

1. Go to [iot.tuya.com](https://iot.tuya.com) and create a free account.
2. Click **Cloud → Development → Create Cloud Project**.
3. Give it a name, set Industry to **Smart Home**, choose the data center closest to you, and click **Create**.
4. On the project page, note your **Access ID** and **Access Secret** — the wizard will ask for these.

**2. Link your Feit app account**

1. In your Tuya project, click **Devices → Link Tuya App Account**.
2. A QR code appears on screen.
3. Open the **Feit Electric app** on your phone, tap **Me** (bottom-right), then tap the scan icon in the top-right corner.
4. Scan the QR code. Your devices will appear in the Tuya project within a few seconds.

**3. Run the tinytuya wizard on the Pi**

```bash
~/WeatherStation/venv/bin/python -m tinytuya wizard
```

Enter your **Access ID**, **Access Secret**, and the **region** when prompted. The wizard scans your local network and saves a `devices.json` file containing the Device ID, IP address, and Local Key for each device.

**4. Copy your plug's credentials into `.env`**

Open `devices.json`, find your Feit plug, and copy the three values into `.env`:

```
PLUG_DEVICE_ID=xxxxxxxxxxxxxxxxxx
PLUG_LOCAL_IP=192.168.1.x
PLUG_LOCAL_KEY=xxxxxxxxxxxxxxxx
TEMP_THRESHOLD_C=25.5
```

Adjust `TEMP_THRESHOLD_C` to your preferred threshold in °C (25.5°C = 78°F).

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

Use the **Session pooler** — not the direct connection. Grafana Cloud connects over IPv4 and the direct connection (`db.xxx.supabase.co:5432`) can fail with an IPv6 error. The session pooler works reliably with Grafana.

1. Open your Supabase project dashboard.
2. Click the green **Connect** button at the top of the page.
3. In the modal, click the **Session pooler** tab.
4. You'll see a connection string like:
   ```
   postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
5. Break it into parts for Grafana:

   | Field | Where to find it | Example |
   |-------|-----------------|---------|
   | **Host** | between `@` and `:5432` | `aws-0-us-east-1.pooler.supabase.com` |
   | **Port** | `5432` | `5432` |
   | **Database** | after the last `/` | `postgres` |
   | **User** | between `//` and `:` | `postgres.xxxxxxxxxxxx` *(note: includes your project ref)* |
   | **Password** | your Supabase project password | *(what you set in Step 4)* |

> **Important:** The username for the pooler is `postgres.yourprojectref` — not just `postgres`. Copy it exactly from the connection string.

---

### 9.3 Add PostgreSQL as a data source

1. In your Grafana instance, click the **hamburger menu (☰)** in the top-left → **Connections → Data sources**.
2. Click **Add new data source**.
3. Search for **PostgreSQL** and click it.
4. Fill in the fields:

   | Field | Value |
   |-------|-------|
   | **Name** | `Supabase` (or any name you like) |
   | **Host URL** | `aws-0-us-east-1.pooler.supabase.com:5432` *(use your actual pooler host from Step 9.2)* |
   | **Database name** | `postgres` |
   | **Username** | `postgres.xxxxxxxxxxxx` *(full username from the pooler string — includes project ref)* |
   | **Password** | your Supabase database password |
   | **TLS/SSL Mode** | `require` |
   | **PostgreSQL version** | `15` |

5. Leave everything else as default.
6. Scroll to the bottom and click **Save & test**.
7. You should see a green banner: **"Database Connection OK"**. If you see an error, double-check the host (no `https://`, no trailing slash) and password.

---

### 9.4 How to add a panel (applies to all dashboards below)

1. Click **☰ → Dashboards → New → New dashboard**.
2. Click **Add visualization**.
3. Select **Supabase** as the data source.
4. Switch the query editor from **Builder** to **Code** mode (toggle in the top-right of the query panel).
5. Paste the SQL query.
6. Set **Panel type** to **Time series** (top-right dropdown).
7. Set the panel title under **Panel options** on the right.
8. Click **Apply**.
9. Repeat for each additional panel, using **Add → Visualization**.
10. Click the **Save** icon, name the dashboard, and click **Save**.

---

### 9.5 Dashboard 1 — Real-time (last 2 hours)

Set the dashboard **auto-refresh** to `30s` using the clock icon in the top-right toolbar.

**Panel: Temperature**
```sql
SELECT
  ts AS time,
  (temperature_c * 9.0/5.0 + 32) AS "Temperature (°F)"
FROM readings
WHERE ts > NOW() - INTERVAL '2 hours'
ORDER BY ts;
```

**Panel: Pressure**
```sql
SELECT
  ts AS time,
  pressure_hpa AS "Pressure (hPa)"
FROM readings
WHERE ts > NOW() - INTERVAL '2 hours'
ORDER BY ts;
```

Save this dashboard as **"Real-time"**.

---

### 9.6 Dashboard 2 — Hourly Averages (last 7 days)

**Panel: Avg Temperature per Hour**
```sql
SELECT
  date_trunc('hour', ts) AS time,
  ROUND(AVG(temperature_c * 9.0/5.0 + 32)::numeric, 1) AS "Avg Temperature (°F)"
FROM readings
WHERE ts > NOW() - INTERVAL '7 days'
GROUP BY date_trunc('hour', ts)
ORDER BY time;
```

**Panel: Avg Pressure per Hour**
```sql
SELECT
  date_trunc('hour', ts) AS time,
  ROUND(AVG(pressure_hpa)::numeric, 1) AS "Avg Pressure (hPa)"
FROM readings
WHERE ts > NOW() - INTERVAL '7 days'
GROUP BY date_trunc('hour', ts)
ORDER BY time;
```

Save this dashboard as **"Hourly Averages"**.

---

### 9.7 Dashboard 3 — Daily Highs & Lows (last 30 days)

**Panel: Daily Temperature High & Low**
```sql
SELECT
  date_trunc('day', ts) AS time,
  ROUND(MAX(temperature_c * 9.0/5.0 + 32)::numeric, 1) AS "High (°F)",
  ROUND(MIN(temperature_c * 9.0/5.0 + 32)::numeric, 1) AS "Low (°F)"
FROM readings
WHERE ts > NOW() - INTERVAL '30 days'
GROUP BY date_trunc('day', ts)
ORDER BY time;
```

**Panel: Daily Pressure High & Low**
```sql
SELECT
  date_trunc('day', ts) AS time,
  ROUND(MAX(pressure_hpa)::numeric, 1) AS "High (hPa)",
  ROUND(MIN(pressure_hpa)::numeric, 1) AS "Low (hPa)"
FROM readings
WHERE ts > NOW() - INTERVAL '30 days'
GROUP BY date_trunc('day', ts)
ORDER BY time;
```

Save this dashboard as **"Daily Highs & Lows"**.

---

### 9.8 Make a dashboard public (optional)

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
0 2 * * * rclone copy /home/ashishnarain/WeatherStation/weather.db gdrive:weather-backups/
```

---

## Step 11: Set Up the Web Dashboard

The web dashboard runs on the Pi and is accessible from any device on your home network. It shows the current temperature and pressure, fan on/off status, and lets you update the fan threshold — all in real time.

### 11.1 Enable and start the webapp service

```bash
sudo cp ~/WeatherStation/systemd/webapp.service /etc/systemd/system/webapp.service
sudo systemctl daemon-reload
sudo systemctl enable webapp
sudo systemctl start webapp
```

### 11.2 Open the dashboard

From any device on your home WiFi, open:

```
http://<pi-ip-address>:5000
```

To find the Pi's IP address:

```bash
hostname -I
```

The dashboard:
- Shows temperature (°F) and pressure — **auto-refreshes every 5 seconds**
- Shows whether the fan/plug is ON or OFF
- Lets you update the fan threshold in °F — **takes effect within 5 seconds**

### 11.3 Update the fan threshold from the command line

You can also update the threshold directly on the Pi:

```bash
# Check current threshold
~/WeatherStation/set-threshold.sh

# Set a new threshold (in °C)
~/WeatherStation/set-threshold.sh 25.5
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
| Plug control disabled in logs | Check that `PLUG_DEVICE_ID`, `PLUG_LOCAL_IP`, and `PLUG_LOCAL_KEY` are all set in `.env` |
| Plug doesn't switch / connection refused | Confirm the plug's IP hasn't changed (assign a static IP in your router); check the Local Key matches `devices.json` |
| `tinytuya wizard` finds no devices | Make sure the Pi and the plug are on the same WiFi network |
| Web dashboard not loading | Run `sudo systemctl status webapp` — check it's active and listening on port 5000 |
| Dashboard shows "Could not reach the station" | Confirm the webapp service is running; check firewall isn't blocking port 5000 |

---

## What Runs Automatically

Once setup is complete, everything runs without any manual intervention:

- **Every 60 seconds**: temperature and pressure logged to `weather.db`
- **Every 5 minutes**: new readings synced to Supabase
- **On reboot**: both services start automatically via systemd
- **On network drop**: pusher replays any missed rows when connectivity returns
- **Every night at 2 AM**: `weather.db` backed up to Google Drive
- **On each reading (if plug configured)**: Feit plug turns ON above threshold, OFF below
- **Always on**: web dashboard available at `http://<pi-ip>:5000` — refreshes every 5 seconds
