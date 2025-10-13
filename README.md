# Alarmmonitor JRK

Komplettlösung für einen webbasierten Alarmmonitor und ein Leitstellen-Interface.

## Features
- Anzeige und Verwaltung von Fahrzeugen mit deutschen Rettungsdienst-Statuscodes
- Leitstellenoberfläche zum Setzen von Status sowie zum Auslösen von Alarmen mit Stichwort, Einsatzort, Koordinaten und Auswahl mehrerer Fahrzeuge
- Farbige Darstellung der Status für schnelle Übersicht
- Persistente Speicherung der Fahrzeugdaten in `data/vehicles.json`
- Alarmgong und Sprachausgabe des Alarmtextes bei neuen Einsätzen (Web Speech API mit Google TTS-Fallback, auch auf iOS/macOS)
- Fahrzeugverwaltung zum Hinzufügen und Entfernen von Einheiten inklusive Funkrufnamen und Besatzung
- Einsatzdokumentation in `data/incidents.json` mit Einsatztagebuch, Fahrzeugzuordnung und manueller Start/Beendigung
- Alarmmonitor im Vollbildmodus mit Kartenansicht, Fahrzeugpositionen und versteckter Menüleiste im Vollbild
- Permanente Backend-Verbindungsanzeige inklusive Hostinformationen – auch im Vollbild sichtbar
- Konfigurierbarer Einsatzbereich mit automatischer Zentrierung der Kartenansichten sowie Wetteranzeige für den gewählten Ort
- Kartengestützte Einsatzortwahl in der Leitstelle mit Zoom und Reverse-Geocoding
- Installationsskript für virtuelle Umgebung und Startskript

### Alarmgong hinzufügen

Die Audiodatei ist aus dem Repository ausgeschlossen. Lege eine passende
`gong.wav` unter `static/` ab, damit der Alarmton abgespielt wird.

## Installation
```bash
./install.sh
```

## Start
```bash
./start.sh
```

### Automatischer Neustart (systemd)

Damit der Dienst nach einem Absturz oder Neustart des Raspberry Pi automatisch
wieder gestartet wird, kann die beiliegende systemd-Unit verwendet werden:

1. Datei `systemd/alarmmonitor.service` nach `/etc/systemd/system/`
   kopieren und Pfade (`WorkingDirectory`, `ExecStart`) sowie Benutzer/Gruppe
   an die eigene Umgebung anpassen.
2. Dienst aktivieren und starten:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable alarmmonitor.service
   sudo systemctl start alarmmonitor.service
   ```

Systemd sorgt anschließend dafür, dass die Anwendung bei Fehlern automatisch
neu gestartet wird.

## Update
```bash
./update.sh
```

Anschließend erreichbar unter:
- Alarmmonitor: http://localhost:5000/
- Leitstelle: http://localhost:5000/dispatch
- Fahrzeugverwaltung: http://localhost:5000/vehicles
- Einsatzdokumentation: http://localhost:5000/incidents
