#!/bin/bash
set -e
if [ ! -d "venv" ]; then
  echo "Virtual environment not found. Run ./install.sh first."
  exit 1
fi
PIDS=$(pgrep -f "flask run --host=0.0.0.0 --port=5000" | tr '\n' ' ' || true)
if [ -z "$PIDS" ]; then
  echo "No running Alarmmonitor Flask process found."
  exit 0
fi
echo "Stopping Alarmmonitor Flask process: $PIDS"
kill -- $PIDS
