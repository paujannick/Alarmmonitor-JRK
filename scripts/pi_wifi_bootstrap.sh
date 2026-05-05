#!/bin/bash
set -euo pipefail
HOTSPOT_NAME="${ALARMMONITOR_HOTSPOT_SSID:-Alarmmonitor-Setup}"
HOTSPOT_PASS="${ALARMMONITOR_HOTSPOT_PASSWORD:-alarmmonitor123}"
CON_NAME="Alarmmonitor-Setup-AP"

if ! command -v nmcli >/dev/null 2>&1; then
  exit 0
fi

if nmcli -t -f STATE g | grep -q '^connected$'; then
  nmcli con down "$CON_NAME" >/dev/null 2>&1 || true
  exit 0
fi

if ! nmcli con show "$CON_NAME" >/dev/null 2>&1; then
  nmcli dev wifi hotspot ifname wlan0 con-name "$CON_NAME" ssid "$HOTSPOT_NAME" password "$HOTSPOT_PASS" >/dev/null 2>&1 || true
else
  nmcli con up "$CON_NAME" >/dev/null 2>&1 || true
fi
