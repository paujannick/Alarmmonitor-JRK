#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

VENV_DIR="${ALARMMONITOR_VENV:-$SCRIPT_DIR/venv}"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Virtual environment not found. Run ./install.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

missing_pager_modules=$(python - <<'PY_CHECK'
import importlib.util

print(' '.join(module for module in ('pigpio', 'spidev') if importlib.util.find_spec(module) is None))
PY_CHECK
)

if [[ -n "$missing_pager_modules" ]]; then
  echo "⚠️  Pager-Hardware-Abhängigkeiten fehlen in der venv: $missing_pager_modules" >&2
  echo "    Die Web-Oberfläche startet trotzdem; Pager-Senden benötigt diese Pakete." >&2
  echo "    Auf Raspberry Pi OS ausführen: sudo apt-get install -y pigpio python3-pigpio python3-spidev && ./install.sh" >&2
fi

export FLASK_APP=app.py
# Creates a local setup Wi‑Fi hotspot when no WLAN uplink is connected.
./scripts/pi_wifi_bootstrap.sh || true
exec flask run --host=0.0.0.0 --port=5000
