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

systemd_unit_exists() {
  local unit_name="$1"
  systemctl list-unit-files "$unit_name" --no-legend 2>/dev/null | awk '{print $1}' | grep -Fxq "$unit_name"
}

apt_package_has_candidate() {
  local package="$1"
  local candidate

  candidate=$(apt-cache policy "$package" 2>/dev/null | awk '/Candidate:/ {print $2; exit}')
  [[ -n "$candidate" && "$candidate" != "(none)" ]]
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

  local failed=0
  local package
  for package in "$@"; do
    if ! apt_package_has_candidate "$package"; then
      echo "⚠️  apt-Paket $package ist in den aktiven Paketquellen nicht verfügbar; überspringe." >&2
      failed=1
      continue
    fi

    if ! run_root apt-get install -y "$package"; then
      echo "⚠️  apt-Paket $package konnte nicht installiert werden; fahre fort." >&2
      failed=1
    fi
  done

  return "$failed"
}

install_pigpio_from_source_if_missing() {
  if command -v pigpiod >/dev/null 2>&1; then
    return 0
  fi

  if ! command -v git >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1 || ! command -v gcc >/dev/null 2>&1; then
    install_apt_package_group "Build-Abhängigkeiten für pigpio" \
      git \
      make \
      gcc || true
  fi

  if ! command -v git >/dev/null 2>&1 || ! command -v make >/dev/null 2>&1 || ! command -v gcc >/dev/null 2>&1; then
    echo "⚠️  pigpio kann nicht aus dem Quellcode gebaut werden; git, make oder gcc fehlen." >&2
    return 1
  fi

  echo "📡 pigpio ist per apt nicht verfügbar; baue und installiere pigpio aus dem Quellcode"

  local build_dir
  build_dir=$(mktemp -d)
  trap 'rm -rf "$build_dir"' RETURN
  (
    cd "$build_dir"
    git clone --depth 1 https://github.com/joan2937/pigpio.git
    cd pigpio
    run_root killall pigpiod >/dev/null 2>&1 || true
    make
    run_root make install
  )

  install_pigpiod_service_if_missing
}

install_pigpiod_service_if_missing() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi

  if systemd_unit_exists pigpiod.service; then
    return 0
  fi

  if [[ ! -x /usr/local/bin/pigpiod ]]; then
    return 0
  fi

  echo "📡 Lege pigpiod.service für aus Quellcode installiertes pigpio an"
  run_root tee /etc/systemd/system/pigpiod.service >/dev/null <<'SERVICE'
[Unit]
Description=Daemon required to control GPIO pins via pigpio
After=network.target

[Service]
ExecStart=/usr/local/bin/pigpiod
ExecStop=/bin/systemctl kill -s SIGKILL pigpiod
Type=forking

[Install]
WantedBy=multi-user.target
SERVICE
  run_root systemctl daemon-reload
}

install_apt_dependencies() {
  install_apt_package_group "Basis-System-Abhängigkeiten" \
    git \
    python3 \
    python3-pip \
    python3-venv \
    network-manager || true

  # Hardware-Pakete sind auf Raspberry Pi OS per apt verfügbar, aber nicht auf
  # allen Debian/Ubuntu-Varianten. Wenn pigpio/pigpiod nicht per apt verfügbar
  # ist, wird es danach aus dem Quellcode gebaut, damit Pager-Senden funktioniert.
  install_apt_package_group "Pager-Hardware-Abhängigkeiten" \
    pigpio \
    python3-pigpio \
    python3-spidev || true

  install_pigpio_from_source_if_missing || true
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

  if systemd_unit_exists pigpiod.service; then
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

  if ! python -m pip install -r "$PROJECT_ROOT/requirements.txt"; then
    echo "⚠️  requirements.txt konnte nicht in einem Lauf installiert werden; versuche Pakete einzeln." >&2
    local requirement
    while IFS= read -r requirement || [[ -n "$requirement" ]]; do
      requirement="${requirement%%#*}"
      requirement="$(xargs <<<"$requirement")"
      if [[ -z "$requirement" ]]; then
        continue
      fi
      if ! python -m pip install "$requirement"; then
        echo "⚠️  $requirement konnte nicht per pip installiert werden; prüfe apt/system-site-packages." >&2
      fi
    done < "$PROJECT_ROOT/requirements.txt"
  fi

  local missing
  missing=$(python - <<'PY_CHECK'
import importlib.util

modules = {
    'Flask': 'flask',
    'RPi.GPIO': 'RPi.GPIO',
    'spidev': 'spidev',
    'pigpio': 'pigpio',
}
print(' '.join(requirement for requirement, module in modules.items() if importlib.util.find_spec(module) is None))
PY_CHECK
)

  if [[ -n "$missing" ]]; then
    echo "⚠️  Python-Pakete fehlen in der venv: $missing" >&2
    echo "    Auf Raspberry Pi OS bitte prüfen: sudo apt-get install -y pigpio python3-pigpio python3-spidev" >&2
    echo "    Die Web-Oberfläche benötigt Flask; Pager-Senden benötigt RPi.GPIO, pigpio und spidev." >&2
    return 1
  fi
}

restart_alarmmonitor_if_installed() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return
  fi

  if systemd_unit_exists "$SERVICE_NAME"; then
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
