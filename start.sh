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

modules = {'RPi.GPIO': 'RPi.GPIO', 'pigpio': 'pigpio', 'spidev': 'spidev'}
print(' '.join(name for name, module in modules.items() if importlib.util.find_spec(module) is None))
PY_CHECK
)

if [[ -n "$missing_pager_modules" ]]; then
  echo "⚠️  Pager-Hardware-Abhängigkeiten fehlen in der venv: $missing_pager_modules" >&2
  echo "    Die Web-Oberfläche startet trotzdem; Pager-Senden benötigt diese Pakete." >&2
  echo "    Auf Raspberry Pi OS ausführen: sudo apt-get install -y pigpio python3-pigpio python3-spidev && ./install.sh" >&2
fi

run_root() {
  if command -v sudo >/dev/null 2>&1 && [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    sudo "$@"
  else
    "$@"
  fi
}

ensure_pigpiod_running() {
  if [[ -n "$missing_pager_modules" ]]; then
    return
  fi

  if ! command -v systemctl >/dev/null 2>&1; then
    echo "⚠️  systemctl nicht verfügbar; pigpiod kann nicht automatisch gestartet werden." >&2
    return
  fi

  if ! systemctl list-unit-files pigpiod.service >/dev/null 2>&1; then
    echo "⚠️  pigpiod.service ist nicht installiert; Pager-Senden benötigt pigpio." >&2
    echo "    Auf Raspberry Pi OS ausführen: sudo apt-get install -y pigpio python3-pigpio" >&2
    return
  fi

  if ! systemctl is-active --quiet pigpiod.service; then
    echo "📡 Starte pigpiod für Pager-Hardware"
    if ! run_root systemctl enable --now pigpiod.service; then
      echo "⚠️  pigpiod konnte nicht gestartet werden; Pager-Senden wird fehlschlagen." >&2
      return
    fi
  fi

  for _ in {1..20}; do
    if python - <<'PY_CHECK'
import pigpio
pi = pigpio.pi()
connected = bool(pi.connected)
pi.stop()
raise SystemExit(0 if connected else 1)
PY_CHECK
    then
      return
    fi
    sleep 0.25
  done

  echo "⚠️  pigpiod läuft, ist aber auf Port 8888 noch nicht erreichbar." >&2
}

export FLASK_APP=app.py
ensure_pigpiod_running
# Creates a local setup Wi‑Fi hotspot when no WLAN uplink is connected.
./scripts/pi_wifi_bootstrap.sh || true
exec flask run --host=0.0.0.0 --port=5000
