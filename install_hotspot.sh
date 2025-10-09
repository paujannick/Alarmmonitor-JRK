#!/bin/bash
# Configure the Alarmmonitor hotspot and Wi-Fi onboarding portal.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Dieses Skript muss als root ausgeführt werden." >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PORTAL_DIR=/opt/alarmmonitor-network-portal
VENV_DIR="$PORTAL_DIR/venv"
SSID=${HOTSPOT_SSID:-Alarmmonitor-Setup}
PASSPHRASE=${HOTSPOT_PASSWORD:-Alarmmonitor2024}
PORT=${PORTAL_PORT:-8080}
WIFI_INTERFACE=${WIFI_INTERFACE:-wlan0}
HOTSPOT_IP=${HOTSPOT_IP:-10.20.0.1}
SUBNET=${HOTSPOT_SUBNET:-10.20.0.0/24}
DHCP_RANGE_START=${DHCP_RANGE_START:-10.20.0.10}
DHCP_RANGE_END=${DHCP_RANGE_END:-10.20.0.50}
DHCP_LEASE=${DHCP_LEASE:-12h}
CHECK_INTERVAL=${CHECK_INTERVAL:-15}
if [[ $SUBNET == */* ]]; then
    HOTSPOT_PREFIX=${SUBNET#*/}
else
    HOTSPOT_PREFIX=24
fi
if ! [[ $HOTSPOT_PREFIX =~ ^[0-9]+$ ]]; then
    HOTSPOT_PREFIX=24
fi
PORTAL_SECRET=${PORTAL_SECRET:-$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)}

if [[ ${#PASSPHRASE} -lt 8 ]]; then
    echo "Das Hotspot-Passwort muss mindestens 8 Zeichen lang sein (aktuell ${#PASSPHRASE})." >&2
    exit 1
fi

apt-get update
apt-get install -y hostapd dnsmasq python3-venv iw wireless-tools iproute2

systemctl stop hostapd || true
systemctl stop dnsmasq || true
systemctl disable hostapd || true
systemctl disable dnsmasq || true

install -d -m 755 "$PORTAL_DIR"
cp "$SCRIPT_DIR/network_portal.py" "$PORTAL_DIR/"
install -d -m 755 "$PORTAL_DIR/templates"
cp "$SCRIPT_DIR/templates/network_portal.html" "$PORTAL_DIR/templates/"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install Flask

install -D -m 750 "$SCRIPT_DIR/scripts/alarmmonitor-network-manager.sh" /usr/local/sbin/alarmmonitor-network-manager.sh

install -D -m 644 "$SCRIPT_DIR/systemd/hostapd-alarmmonitor.service" /etc/systemd/system/hostapd-alarmmonitor.service
install -D -m 644 "$SCRIPT_DIR/systemd/dnsmasq-alarmmonitor.service" /etc/systemd/system/dnsmasq-alarmmonitor.service
install -D -m 644 "$SCRIPT_DIR/systemd/alarmmonitor-network-portal.service" /etc/systemd/system/alarmmonitor-network-portal.service
install -D -m 644 "$SCRIPT_DIR/systemd/alarmmonitor-network-manager.service" /etc/systemd/system/alarmmonitor-network-manager.service

sed -i "s|Environment=WIFI_INTERFACE=.*|Environment=WIFI_INTERFACE=$WIFI_INTERFACE|" /etc/systemd/system/alarmmonitor-network-portal.service
sed -i "s|Environment=PORTAL_PORT=.*|Environment=PORTAL_PORT=$PORT|" /etc/systemd/system/alarmmonitor-network-portal.service
sed -i "s|Environment=PORTAL_SECRET=.*|Environment=PORTAL_SECRET=$PORTAL_SECRET|" /etc/systemd/system/alarmmonitor-network-portal.service
if grep -q "Environment=HOTSPOT_SUBNET" /etc/systemd/system/alarmmonitor-network-portal.service; then
    sed -i "s|Environment=HOTSPOT_SUBNET=.*|Environment=HOTSPOT_SUBNET=$SUBNET|" /etc/systemd/system/alarmmonitor-network-portal.service
else
    sed -i "/Environment=WPA_SUPPLICANT_CONF=/a Environment=HOTSPOT_SUBNET=$SUBNET" /etc/systemd/system/alarmmonitor-network-portal.service
fi

sed -i "s|Environment=WIFI_INTERFACE=.*|Environment=WIFI_INTERFACE=$WIFI_INTERFACE|" /etc/systemd/system/alarmmonitor-network-manager.service
sed -i "s|Environment=HOTSPOT_IP=.*|Environment=HOTSPOT_IP=$HOTSPOT_IP|" /etc/systemd/system/alarmmonitor-network-manager.service
sed -i "s|Environment=CHECK_INTERVAL=.*|Environment=CHECK_INTERVAL=$CHECK_INTERVAL|" /etc/systemd/system/alarmmonitor-network-manager.service
sed -i "s|Environment=HOTSPOT_PREFIX=.*|Environment=HOTSPOT_PREFIX=$HOTSPOT_PREFIX|" /etc/systemd/system/alarmmonitor-network-manager.service

cat <<CONF > /etc/hostapd/hostapd-alarmmonitor.conf
interface=$WIFI_INTERFACE
driver=nl80211
ssid=$SSID
hw_mode=g
channel=6
ieee80211n=1
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$PASSPHRASE
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
CONF

cat <<CONF > /etc/dnsmasq.d/alarmmonitor.conf
interface=$WIFI_INTERFACE
bind-interfaces
dhcp-range=$DHCP_RANGE_START,$DHCP_RANGE_END,$DHCP_LEASE
dhcp-option=option:router,$HOTSPOT_IP
dhcp-option=option:dns-server,$HOTSPOT_IP
log-facility=/var/log/dnsmasq-alarmmonitor.log
CONF

chmod 600 /etc/hostapd/hostapd-alarmmonitor.conf
touch /var/log/dnsmasq-alarmmonitor.log
chmod 640 /var/log/dnsmasq-alarmmonitor.log

systemctl daemon-reload
systemctl enable alarmmonitor-network-manager.service
systemctl restart alarmmonitor-network-manager.service

cat <<INFO
Die Hotspot-Konfiguration wurde eingerichtet.

SSID: $SSID
Hotspot-IP: $HOTSPOT_IP
Subnetz: $SUBNET
Portal: http://$HOTSPOT_IP:$PORT/

Der Hotspot wird automatisch gestartet, wenn keine bekannte WLAN-Verbindung besteht.
INFO
