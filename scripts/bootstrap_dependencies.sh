#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR="${ALARMMONITOR_VENV:-$PROJECT_ROOT/venv}"
SERVICE_NAME="${ALARMMONITOR_SERVICE_NAME:-alarmmonitor.service}"
APT_UPDATED=0

if command -v sudo >/dev/null 2>&1 && [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

run_root() {
  if [[ -n "$SUDO" ]]; then
    $SUDO "$@"
  else
    "$@"
  fi
}

apt_update_once() {
  if [[ "$APT_UPDATED" -eq 0 ]]; then
    run_root apt-get update
    APT_UPDATED=1
  fi
}

install_apt_package_group() {
  local description="$1"
  shift

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get nicht gefunden, überspringe $description."
    return 1
  fi

  echo "📦 Installiere $description"
  apt_update_once
  if run_root apt-get install -y "$@"; then
    return 0
  fi

  echo "⚠️  $description konnte nicht vollständig per apt installiert werden; fahre fort." >&2
  return 1
}

install_apt_dependencies() {
  install_apt_package_group "Basis-System-Abhängigkeiten" \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    network-manager || true

  # Hardware-Pakete sind auf Raspberry Pi OS per apt verfügbar, aber nicht auf
  # allen Debian/Ubuntu-Varianten. Ein Fehlschlag darf die Web-App-Installation
  # nicht abbrechen; pip bzw. die Laufzeitprüfung übernehmen den Fallback.
  install_apt_package_group "Pager-Hardware-Abhängigkeiten" \
    pigpio \
    python3-pigpio \
    python3-spidev || true
}

enable_spi_if_available() {
  if command -v raspi-config >/dev/null 2>&1; then
    echo "🔌 Aktiviere SPI-Schnittstelle"
    run_root raspi-config nonint do_spi 0 || true
  fi
}

ensure_pigpiod_started() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return
  fi

  if systemctl list-unit-files pigpiod.service >/dev/null 2>&1; then
    echo "📡 Aktiviere und starte pigpiod"
    run_root systemctl enable --now pigpiod.service
  fi
}

install_python_dependencies() {
  echo "🐍 Installiere Python-Abhängigkeiten"
  python3 -m venv --system-site-packages "$VENV_DIR"

  # Bestehende venvs wurden ggf. ohne Zugriff auf apt-Pakete wie
  # python3-pigpio erstellt. Aktiviere system-site-packages nachträglich,
  # damit der Pagerdienst pigpio/spidev auf Raspberry Pi zuverlässig findet.
  if [[ -f "$VENV_DIR/pyvenv.cfg" ]] && grep -q "^include-system-site-packages = false" "$VENV_DIR/pyvenv.cfg"; then
    sed -i "s/^include-system-site-packages = false/include-system-site-packages = true/" "$VENV_DIR/pyvenv.cfg"
  fi

  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip setuptools wheel

  # Die venv sieht Systempakete, damit apt-Pakete auf Raspberry Pi OS nutzbar
  # bleiben. Deshalb erzwingen wir bei pip-Paketen eine Installation in genau
  # diese venv, statt globale Pakete als "Requirement already satisfied" zu
  # akzeptieren.
  python -m pip install --upgrade --force-reinstall Flask

  local hardware_package
  for hardware_package in RPi.GPIO spidev pigpio; do
    if ! python -m pip install --upgrade --force-reinstall "$hardware_package"; then
      echo "⚠️  $hardware_package konnte nicht per pip in der venv installiert werden; prüfe apt/system-site-packages." >&2
    fi
  done

  local missing
  missing=$(python - <<'PY_CHECK'
import importlib.util

print(' '.join(module for module in ('pigpio', 'spidev') if importlib.util.find_spec(module) is None))
PY_CHECK
)

  if [[ -n "$missing" ]]; then
    echo "❌ Pager-Hardware-Pythonpakete fehlen weiterhin: $missing" >&2
    echo "   Auf Raspberry Pi OS ausführen: sudo apt-get install -y pigpio python3-pigpio python3-spidev && ./install.sh" >&2
    exit 1
  fi

  python - <<PY_VERIFY
from pathlib import Path
import importlib.util
import sys

venv = Path('$VENV_DIR').resolve()
strict_modules = ('flask', 'pigpio', 'spidev')
for module in strict_modules:
    spec = importlib.util.find_spec(module)
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None:
        raise SystemExit(f'{module} wurde nicht gefunden')
    try:
        origin.relative_to(venv)
    except ValueError:
        if module in {'pigpio', 'spidev'}:
            print(f'ℹ️  {module} kommt aus Systempaketen: {origin}', file=sys.stderr)
        else:
            raise SystemExit(f'{module} wurde nicht in der venv installiert: {origin}')
PY_VERIFY
}

restart_alarmmonitor_if_installed() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return
  fi

  if systemctl list-unit-files "$SERVICE_NAME" >/dev/null 2>&1; then
    echo "🚀 Aktiviere und starte/restartet $SERVICE_NAME"
    run_root systemctl daemon-reload
    run_root systemctl enable "$SERVICE_NAME"
    run_root systemctl restart "$SERVICE_NAME"
  fi
}

main() {
  install_apt_dependencies
  enable_spi_if_available
  ensure_pigpiod_started
  install_python_dependencies
  restart_alarmmonitor_if_installed
}

main "$@"
