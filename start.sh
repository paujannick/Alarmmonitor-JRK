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

missing_pager_modules() {
  python - <<'PY_CHECK'
import importlib.util
import sys

missing = [module for module in ("pigpio", "spidev") if importlib.util.find_spec(module) is None]
if missing:
    print(" ".join(missing))
    sys.exit(1)
PY_CHECK
}

if missing=$(missing_pager_modules); then
  :
else
  echo "Pager-Hardware-Abhängigkeiten fehlen in der venv: $missing" >&2
  echo "Starte automatische Nachinstallation über ./install.sh ..." >&2
  ./install.sh
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  if missing=$(missing_pager_modules); then
    :
  else
    echo "Pager-Hardware-Abhängigkeiten fehlen weiterhin: $missing" >&2
    echo "Bitte auf dem Raspberry Pi ausführen: sudo apt-get install -y pigpio python3-pigpio python3-spidev && ./install.sh" >&2
    exit 1
  fi
fi

export FLASK_APP=app.py
# Creates a local setup Wi‑Fi hotspot when no WLAN uplink is connected.
./scripts/pi_wifi_bootstrap.sh || true
exec flask run --host=0.0.0.0 --port=5000
