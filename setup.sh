#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/venv"

echo "=== Creating Python virtual environment ==="
sudo apt install -y python3-full python3-venv
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

echo "=== Enabling I2C ==="
sudo raspi-config nonint do_i2c 0

echo "=== Initialising local database ==="
"$VENV_DIR/bin/python" - <<EOF
import sqlite3, pathlib
db = pathlib.Path("$REPO_DIR/weather.db")
conn = sqlite3.connect(db)
conn.executescript(open("$REPO_DIR/schema.sql").read())
conn.commit()
conn.close()
print("Database ready at", db)
EOF

echo "=== Installing systemd services ==="
# Inject the actual repo path and venv python into the service files
sed "s|/home/pi/WeatherStation|$REPO_DIR|g" \
    "$REPO_DIR/systemd/collector.service" | sudo tee /etc/systemd/system/collector.service > /dev/null
sed "s|/home/pi/WeatherStation|$REPO_DIR|g" \
    "$REPO_DIR/systemd/pusher.service" | sudo tee /etc/systemd/system/pusher.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable collector pusher
sudo systemctl start  collector pusher

echo ""
echo "Done. Check status with:"
echo "  sudo systemctl status collector"
echo "  sudo systemctl status pusher"
