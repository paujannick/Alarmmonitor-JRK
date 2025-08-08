# Alarmmonitor JRK

Webbasierter Alarmmonitor und Leitstellen-Simulator auf Basis von FastAPI.

## Features
- FastAPI Backend mit REST- und WebSocket-Schnittstellen
- Verwaltung von Fahrzeugen und Einsätzen in SQLite (`data/app.db`)
- Zwei Weboberflächen: Leitstelle (`/`) und Monitor (`/monitor`)
- Alarmgong und optionale Sprachausgabe

## Installation
```bash
./scripts/install.sh
```

## Start
```bash
./scripts/start.sh
```

Anschließend erreichbar unter:
- Leitstelle: http://localhost:8080/
- Alarmmonitor: http://localhost:8080/monitor

Lege eine Audiodatei `gong1.mp3` unter `app/assets/sounds/` ab, damit der Alarmton abgespielt wird.
