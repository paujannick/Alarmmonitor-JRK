#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT="$SCRIPT_DIR"
TARGET_DIR="$PROJECT_ROOT"
SERVICE_NAME="alarmmonitor"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ -n "${SUDO_USER:-}" && ${EUID:-$(id -u)} -eq 0 ]]; then
  DEFAULT_SERVICE_USER="$SUDO_USER"
elif [[ ${EUID:-$(id -u)} -eq 0 ]]; then
  DEFAULT_SERVICE_USER="root"
else
  DEFAULT_SERVICE_USER="$(id -un)"
fi

SERVICE_USER="${SERVICE_USER:-$DEFAULT_SERVICE_USER}"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Der Benutzer '$SERVICE_USER' existiert nicht." >&2
  exit 1
fi

DEFAULT_SERVICE_GROUP=$(id -gn "$SERVICE_USER")
SERVICE_GROUP="${SERVICE_GROUP:-$DEFAULT_SERVICE_GROUP}"

if command -v sudo >/dev/null 2>&1; then
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    SUDO="sudo"
  else
    SUDO="sudo"
  fi
else
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    echo "Dieses Setup benötigt administrative Rechte. Bitte sudo installieren oder als root ausführen." >&2
    exit 1
  fi
  SUDO=""
fi

require_commands() {
  local missing=()
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    echo "Es fehlen erforderliche Programme: ${missing[*]}" >&2
    exit 1
  fi
}

require_commands python3 systemctl

if [[ ! -f "$PROJECT_ROOT/install.sh" || ! -f "$PROJECT_ROOT/start.sh" ]]; then
  echo "install.sh oder start.sh wurden nicht gefunden." >&2
  exit 1
fi

run_as_service_user() {
  local cmd="$1"
  if [[ $(id -un) == "$SERVICE_USER" ]]; then
    bash -lc "$cmd"
  elif command -v sudo >/dev/null 2>&1; then
    sudo -u "$SERVICE_USER" bash -lc "$cmd"
  elif command -v runuser >/dev/null 2>&1; then
    runuser -u "$SERVICE_USER" -- bash -lc "$cmd"
  else
    su - "$SERVICE_USER" -c "$cmd"
  fi
}

prepare_project_directory() {
  echo "\n📂 Verwende Projektverzeichnis $TARGET_DIR"
  if [[ "$TARGET_DIR" != "$PROJECT_ROOT" ]]; then
    echo "Das Projekt muss im ursprünglichen Git-Verzeichnis bleiben." >&2
    exit 1
  fi
  $SUDO chown -R "$SERVICE_USER:$SERVICE_GROUP" "$TARGET_DIR"
  $SUDO chmod +x "$TARGET_DIR/start.sh" "$TARGET_DIR/install.sh"
}

setup_virtualenv() {
  echo "\n🐍 Installiere Python-Abhängigkeiten"
  run_as_service_user "cd '$TARGET_DIR' && ./install.sh"
}

create_service_file() {
  echo "\n🛠️ Erstelle systemd Service-Datei"
  local tmpfile
  tmpfile=$(mktemp)
  cat > "$tmpfile" <<SERVICE
[Unit]
Description=Alarmmonitor JRK
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$TARGET_DIR
ExecStart=/usr/bin/env bash $TARGET_DIR/start.sh
Restart=always
RestartSec=5
Environment=FLASK_ENV=production
User=$SERVICE_USER
Group=$SERVICE_GROUP

[Install]
WantedBy=multi-user.target
SERVICE
  $SUDO mv "$tmpfile" "$SERVICE_FILE"
  $SUDO chmod 644 "$SERVICE_FILE"
}

enable_service() {
  echo "\n🚀 Aktiviere und starte den Dienst"
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now "$SERVICE_NAME.service"
}

main() {
  echo "ℹ️  Dienst läuft als $SERVICE_USER:$SERVICE_GROUP"
  echo "📁 Zielverzeichnis: $TARGET_DIR"
  prepare_project_directory
  setup_virtualenv
  create_service_file
  enable_service
  echo "\n✅ Autostart-Setup abgeschlossen. Dienststatus:"
  $SUDO systemctl status "$SERVICE_NAME.service" --no-pager || true
}

main "$@"
