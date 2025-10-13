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

Das Skript `setup_autostart.sh` richtet den Dienst vollständig ein: Es kopiert
den Quellcode nach `/opt/alarmmonitor` (oder ein optional übergebenes
Zielverzeichnis), installiert die Abhängigkeiten im Ziel und erstellt sowie
aktiviert eine passende `systemd`-Unit. Ausführen mit:

```bash
./setup_autostart.sh
```

Standardmäßig läuft der Dienst unter dem Benutzer, der das Skript aufruft (bei
`sudo` wird automatisch `SUDO_USER` verwendet). Ein anderes Zielverzeichnis
kann als Parameter übergeben werden:

```bash
./setup_autostart.sh /srv/alarmmonitor
```

Nach erfolgreichem Durchlauf ist der Dienst `alarmmonitor.service` bereits
aktiviert und gestartet. Die zuvor mitgelieferte Beispiel-Unit liegt weiterhin
unter `systemd/alarmmonitor.service`, falls sie separat angepasst werden soll.

## Update
```bash
./update.sh
```

Anschließend erreichbar unter:
- Alarmmonitor: http://localhost:5000/
- Leitstelle: http://localhost:5000/dispatch
- Fahrzeugverwaltung: http://localhost:5000/vehicles
- Einsatzdokumentation: http://localhost:5000/incidents
