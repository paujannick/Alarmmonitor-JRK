#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR="${ALARMMONITOR_VENV:-$PROJECT_ROOT/venv}"
SERVICE_NAME="${ALARMMONITOR_SERVICE_NAME:-alarmmonitor.service}"

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

install_apt_dependencies() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get nicht gefunden, überspringe Systempakete."
    return
  fi

  echo "📦 Installiere System-Abhängigkeiten"
  run_root apt-get update
  run_root apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    pigpio \
    python3-pigpio \
    python3-spidev \
    network-manager
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
  python3 -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -r "$PROJECT_ROOT/requirements.txt"
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
