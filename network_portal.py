"""Lightweight Wi-Fi configuration portal used while the Alarmmonitor hotspot is active.

The portal is designed to run with root privileges on a Raspberry Pi.  It exposes a
minimal web UI to scan for nearby WLANs, store credentials via wpa_cli and trigger a
reconfiguration of wpa_supplicant.  The application is meant to be launched only while
an access point is active so that end users can provide the credentials for the local
network.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)


def get_env(name: str, default: str) -> str:
    value = os.environ.get(name, "")
    return value if value else default


APP_ROOT = Path(__file__).resolve().parent
TEMPLATE_ROOT = APP_ROOT / "templates"

app = Flask(__name__, template_folder=str(TEMPLATE_ROOT))
app.secret_key = os.environ.get("PORTAL_SECRET", "alarmmonitor-network-portal")

WIFI_INTERFACE = get_env("WIFI_INTERFACE", "wlan0")
WPA_SUPPLICANT_CONF = Path(
    get_env("WPA_SUPPLICANT_CONF", "/etc/wpa_supplicant/wpa_supplicant.conf")
)
SCAN_COMMAND = shlex.split(get_env("WIFI_SCAN_COMMAND", f"iwlist {WIFI_INTERFACE} scan"))


class PortalError(RuntimeError):
    """Domain specific exception to signal failures to the user."""


def run_command(command: List[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise PortalError(
            f"Der benötigte Befehl '{command[0]}' ist auf dem System nicht verfügbar."
        ) from exc


def run_wpa_cli(*args: str) -> str:
    command = ["wpa_cli", "-i", WIFI_INTERFACE, *args]
    result = run_command(command)
    return result.stdout.strip()


def list_configured_networks() -> List[Dict[str, str]]:
    try:
        output = run_wpa_cli("list_networks")
    except (PortalError, subprocess.CalledProcessError) as exc:  # pragma: no cover - hardware specific
        app.logger.warning("Unable to list configured networks: %s", exc)
        return []
    entries: List[Dict[str, str]] = []
    lines = [line for line in output.splitlines() if line.strip()]
    # First line is the header (network id / ssid / bssid / flags)
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        entries.append(
            {
                "id": fields[0],
                "ssid": fields[1],
                "bssid": fields[2] if fields[2] != "any" else "",
                "flags": fields[3],
            }
        )
    return entries


def forget_network(network_id: str) -> None:
    run_wpa_cli("remove_network", network_id)
    run_wpa_cli("save_config")
    run_wpa_cli("reconfigure")


def scan_networks() -> List[Dict[str, Optional[str]]]:
    try:
        result = run_command(SCAN_COMMAND)
    except (PortalError, subprocess.CalledProcessError) as exc:  # pragma: no cover - hardware specific
        app.logger.warning("Wi-Fi scan failed: %s", exc)
        return []
    networks: List[Dict[str, Optional[str]]] = []
    current: Dict[str, Optional[str]] = {}
    essid_pattern = re.compile(r"ESSID:\"(.*)\"")
    quality_pattern = re.compile(r"Quality=(\d+)/(\d+)")
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("Cell "):
            if current:
                networks.append(current)
            current = {"ssid": None, "quality": None, "secure": "on"}
            continue
        essid_match = essid_pattern.search(line)
        if essid_match:
            current["ssid"] = essid_match.group(1)
            continue
        quality_match = quality_pattern.search(line)
        if quality_match:
            try:
                quality = int(quality_match.group(1))
                total = int(quality_match.group(2))
                current["quality"] = int(quality * 100 / total)
            except (ValueError, ZeroDivisionError):
                current["quality"] = None
            continue
        if line.startswith("Encryption key:"):
            state = line.split(":", 1)[1].strip().lower()
            current["secure"] = "on" if state == "on" else "off"
            continue
        if "IE:" in line and "WPA" in line:
            current["secure"] = "on"
    if current:
        networks.append(current)
    seen: Dict[str, Dict[str, Optional[str]]] = {}
    for network in networks:
        ssid = network.get("ssid") or ""
        if ssid in seen:
            existing_quality = seen[ssid].get("quality")
            current_quality = network.get("quality")
            if (
                existing_quality is None
                or (current_quality is not None and current_quality > existing_quality)
            ):
                seen[ssid] = network
        else:
            seen[ssid] = network
    cleaned = []
    for ssid, data in seen.items():
        cleaned.append(
            {
                "ssid": ssid,
                "quality": data.get("quality"),
                "secure": data.get("secure", "on") != "off",
            }
        )
    cleaned.sort(key=lambda item: (item["quality"] or 0), reverse=True)
    return cleaned


def configure_network(ssid: str, password: str, hidden: bool = False) -> None:
    if not ssid:
        raise PortalError("Die SSID darf nicht leer sein.")
    if password and len(password) < 8:
        raise PortalError("Das WLAN-Passwort muss mindestens 8 Zeichen lang sein.")
    # Determine whether the network already exists.
    networks = list_configured_networks()
    network_id: Optional[str] = None
    for entry in networks:
        if entry.get("ssid") == ssid:
            network_id = entry.get("id")
            break
    if network_id is None:
        network_id = run_wpa_cli("add_network").strip()
    if not network_id:
        raise PortalError("Konnte kein Netzwerkprofil anlegen.")
    run_wpa_cli("set_network", network_id, "ssid", f'"{ssid}"')
    if hidden:
        run_wpa_cli("set_network", network_id, "scan_ssid", "1")
    else:
        run_wpa_cli("set_network", network_id, "scan_ssid", "0")
    if password:
        run_wpa_cli("set_network", network_id, "psk", f'"{password}"')
        run_wpa_cli("set_network", network_id, "key_mgmt", "WPA-PSK")
    else:
        run_wpa_cli("set_network", network_id, "key_mgmt", "NONE")
        run_wpa_cli("set_network", network_id, "psk", "")
    run_wpa_cli("enable_network", network_id)
    run_wpa_cli("select_network", network_id)
    run_wpa_cli("save_config")
    run_wpa_cli("reconfigure")


def current_connection() -> str:
    try:
        result = run_command(["iwgetid", "-r", WIFI_INTERFACE])
    except (PortalError, subprocess.CalledProcessError):  # pragma: no cover - hardware specific
        return ""
    return result.stdout.strip()


def hotspot_subnet() -> str:
    cidr = os.environ.get("HOTSPOT_SUBNET", "10.20.0.0/24")
    try:
        return str(ipaddress.ip_network(cidr, strict=False))
    except ValueError:
        return "10.20.0.0/24"


@app.route("/")
def index():
    networks = scan_networks()
    configured = list_configured_networks()
    active = current_connection()
    return render_template(
        "network_portal.html",
        networks=networks,
        configured_networks=configured,
        active_ssid=active,
        hotspot_subnet=hotspot_subnet(),
    )


@app.post("/connect")
def connect():
    ssid = request.form.get("ssid", "").strip()
    password = request.form.get("password", "").strip()
    hidden = request.form.get("hidden", "off") == "on"
    try:
        configure_network(ssid, password, hidden=hidden)
        flash("Zugangsdaten gespeichert. Der Pi versucht, sich jetzt zu verbinden.")
    except PortalError as exc:
        flash(str(exc), "error")
    except subprocess.CalledProcessError as exc:  # pragma: no cover - hardware specific
        stderr = exc.stderr.strip() if exc.stderr else exc.stdout
        message = stderr or "Unbekannter Fehler bei der Konfiguration."
        app.logger.error("wpa_cli failure: %s", message)
        flash(f"Fehler bei der Konfiguration: {message}", "error")
    return redirect(url_for("index"))


@app.post("/forget/<network_id>")
def forget(network_id: str):
    try:
        forget_network(network_id)
        flash("Netzwerk wurde entfernt.")
    except PortalError as exc:
        flash(str(exc), "error")
    except subprocess.CalledProcessError as exc:  # pragma: no cover - hardware specific
        stderr = exc.stderr.strip() if exc.stderr else exc.stdout
        message = stderr or "Unbekannter Fehler beim Entfernen."
        app.logger.error("wpa_cli failure: %s", message)
        flash(f"Netzwerk konnte nicht entfernt werden: {message}", "error")
    return redirect(url_for("index"))


@app.get("/healthz")
def health_check():
    return {
        "status": "ok",
        "interface": WIFI_INTERFACE,
        "wpa_supplicant": str(WPA_SUPPLICANT_CONF),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORTAL_PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
