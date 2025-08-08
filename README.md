# Alarmmonitor JRK

Komplettlösung für einen webbasierten Alarmmonitor und ein Leitstellen-Interface.

## Features
- Anzeige und Verwaltung von Fahrzeugen mit deutschen Rettungsdienst-Statuscodes
- Leitstellenoberfläche zum Setzen von Status, Alarmtext und Einsatzort
- Farbige Darstellung der Status für schnelle Übersicht
- Persistente Speicherung der Fahrzeugdaten in `data/vehicles.json`
- Alarmgong und Sprachausgabe des Alarmtextes bei neuen Einsätzen
- Installationsskript für virtuelle Umgebung und Startskript

### Alarmgong hinzufügen

Die Audiodatei ist aus dem Repository ausgeschlossen. Lege eine passende
`gong.wav` unter `static/` ab, damit der Alarmton abgespielt wird.

## Installation
```bash
./scripts/install.sh
```

## Start
```bash
./scripts/start.sh
```

Anschließend erreichbar unter:
- Alarmmonitor: http://localhost:5000/
- Leitstelle: http://localhost:5000/dispatch
