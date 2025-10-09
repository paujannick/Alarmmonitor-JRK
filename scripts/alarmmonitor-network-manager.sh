#!/bin/bash
# Manage hotspot and Wi-Fi portal depending on connectivity status.

set -euo pipefail

WIFI_INTERFACE=${WIFI_INTERFACE:-wlan0}
HOTSPOT_IP=${HOTSPOT_IP:-10.20.0.1}
CHECK_INTERVAL=${CHECK_INTERVAL:-15}
HOTSPOT_PREFIX=${HOTSPOT_PREFIX:-24}
HOSTAPD_SERVICE=${HOSTAPD_SERVICE:-hostapd-alarmmonitor.service}
DNSMASQ_SERVICE=${DNSMASQ_SERVICE:-dnsmasq-alarmmonitor.service}
PORTAL_SERVICE=${PORTAL_SERVICE:-alarmmonitor-network-portal.service}
WPA_SUPPLICANT_SERVICE=${WPA_SUPPLICANT_SERVICE:-wpa_supplicant@${WIFI_INTERFACE}.service}
STATE_FILE=/run/alarmmonitor-hotspot.active

log() {
    logger --tag alarmmonitor-network "$*"
}

hotspot_active() {
    [[ -f "$STATE_FILE" ]]
}

mark_hotspot() {
    touch "$STATE_FILE"
}

clear_hotspot() {
    rm -f "$STATE_FILE"
}

bring_down_wifi() {
    ip addr flush dev "$WIFI_INTERFACE" || true
    ip link set "$WIFI_INTERFACE" down || true
}

bring_up_hotspot_interface() {
    ip link set "$WIFI_INTERFACE" up || true
    ip addr add "$HOTSPOT_IP/$HOTSPOT_PREFIX" dev "$WIFI_INTERFACE" || true
}

start_hotspot() {
    if hotspot_active; then
        return 0
    fi
    log "Starting hotspot on ${WIFI_INTERFACE}"
    systemctl stop "$WPA_SUPPLICANT_SERVICE" || true
    bring_down_wifi
    bring_up_hotspot_interface
    systemctl stop hostapd.service || true
    systemctl stop dnsmasq.service || true
    systemctl start "$HOSTAPD_SERVICE"
    systemctl start "$DNSMASQ_SERVICE"
    systemctl start "$PORTAL_SERVICE"
    mark_hotspot
}

stop_hotspot() {
    if ! hotspot_active; then
        return 0
    fi
    log "Stopping hotspot on ${WIFI_INTERFACE}"
    systemctl stop "$PORTAL_SERVICE" || true
    systemctl stop "$DNSMASQ_SERVICE" || true
    systemctl stop "$HOSTAPD_SERVICE" || true
    bring_down_wifi
    clear_hotspot
    systemctl start "$WPA_SUPPLICANT_SERVICE" || true
}

connected_to_wifi() {
    iwgetid -r "$WIFI_INTERFACE" >/dev/null 2>&1
}

trap 'stop_hotspot; exit 0' TERM INT

while true; do
    if connected_to_wifi; then
        stop_hotspot
        if ! hotspot_active; then
            systemctl restart "$WPA_SUPPLICANT_SERVICE" >/dev/null 2>&1 || true
        fi
    else
        start_hotspot
    fi
    sleep "$CHECK_INTERVAL"
done
