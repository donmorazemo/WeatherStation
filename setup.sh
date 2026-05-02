#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing Python dependencies ==="
pip3 install -r "$REPO_DIR/requirements.txt"

echo "=== Enabling I2C ==="
sudo raspi-config nonint do_i2c 0

echo "=== Initialising local database ==="
python3 - <<'EOF'
import sqlite3
from pathlib import Path
db = Path(__file__).parent / "weather.db" if False else Path("weather.db")
conn = sqlite3.connect(db)
conn.executescript(open("schema.sql").read())
conn.commit()
conn.close()
print("Database ready at", db)
EOF

echo "=== Installing systemd services ==="
sudo cp "$REPO_DIR/systemd/collector.service" /etc/systemd/system/
sudo cp "$REPO_DIR/systemd/pusher.service"    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable collector pusher
sudo systemctl start  collector pusher

echo ""
echo "Done. Check status with:"
echo "  sudo systemctl status collector"
echo "  sudo systemctl status pusher"
