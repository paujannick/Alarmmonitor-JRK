#!/bin/bash
set -e
if [ ! -d "venv" ]; then
  echo "Virtual environment not found. Run ./install.sh first."
  exit 1
fi
source venv/bin/activate
export FLASK_APP=app.py
# Creates a local setup Wi‑Fi hotspot when no WLAN uplink is connected.
./scripts/pi_wifi_bootstrap.sh || true
exec flask run --host=0.0.0.0 --port=5000
read -p "Zum Beenden Enter drücken..."
