#!/bin/bash
set -e
if [ ! -d "venv" ]; then
  echo "Virtual environment not found. Run ./install.sh first."
  exit 1
fi
source venv/bin/activate
export FLASK_APP=app.py
# Starte bei Bedarf den Browser einmalig pro Systemstart im Hintergrund.
python3 scripts/launch_browser_once.py &
exec flask run --host=0.0.0.0 --port=5000
