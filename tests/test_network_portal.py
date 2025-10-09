import pytest

import network_portal
from network_portal import app, PortalError


def test_index_handles_missing_wifi_tools(monkeypatch):
    call_log = []

    def fake_run(command, check, text, capture_output):
        call_log.append(command)
        raise FileNotFoundError("missing tool")

    monkeypatch.setattr(network_portal.subprocess, "run", fake_run)

    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Es wurden keine Netzwerke gefunden" in response.data
    assert b"Es sind noch keine WLANs gespeichert" in response.data
    # ensure both scan and list attempts happened
    assert any(cmd[0] == "iwlist" for cmd in call_log)
    assert any(cmd[0] == "wpa_cli" for cmd in call_log)


def test_connect_flashes_error_when_portal_error(monkeypatch):
    def fake_configure(ssid, password, hidden=False):
        raise PortalError("Der benötigte Befehl 'wpa_cli' ist auf dem System nicht verfügbar.")

    monkeypatch.setattr(network_portal, "configure_network", fake_configure)

    client = app.test_client()
    response = client.post("/connect", data={"ssid": "Test", "password": "12345678"})
    assert response.status_code == 302

    with client.session_transaction() as session:
        flashed = session.get("_flashes", [])
    assert flashed
    category, message = flashed[0]
    assert category == "error"
    assert "wpa_cli" in message


def test_forget_flashes_error_when_portal_error(monkeypatch):
    def fake_forget(network_id):
        raise PortalError("Testfehler")

    monkeypatch.setattr(network_portal, "forget_network", fake_forget)

    client = app.test_client()
    response = client.post("/forget/1")
    assert response.status_code == 302
    with client.session_transaction() as session:
        flashed = session.get("_flashes", [])
    assert flashed
    category, message = flashed[0]
    assert category == "error"
    assert "Testfehler" in message
