# Alarmmonitor JRK

Komplettlösung für einen webbasierten Alarmmonitor und ein Leitstellen-Interface.

## Features
- Anzeige und Verwaltung von Fahrzeugen mit deutschen Rettungsdienst-Statuscodes
- Leitstellenoberfläche zum Setzen von Status sowie zum Auslösen von Alarmen mit Stichwort, Einsatzort, Koordinaten und Auswahl mehrerer Fahrzeuge
- Farbige Darstellung der Status für schnelle Übersicht
- Persistente Speicherung der Fahrzeugdaten in `data/vehicles.json`
- Alarmgong und Sprachausgabe des Alarmtextes bei neuen Einsätzen (Web Speech API mit Google TTS-Fallback)
- Fahrzeugverwaltung zum Hinzufügen und Entfernen von Einheiten inklusive Funkrufnamen und Besatzung
- Einsatzdokumentation in `data/incidents.json` mit Einsatztagebuch, Fahrzeugzuordnung und manueller Start/Beendigung
- Alarmmonitor im Vollbildmodus mit Kartenansicht, Fahrzeugpositionen und versteckter Menüleiste im Vollbild
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

## Update
```bash
./update.sh
```

Anschließend erreichbar unter:
- Alarmmonitor: http://localhost:5000/
- Leitstelle: http://localhost:5000/dispatch
- Fahrzeugverwaltung: http://localhost:5000/vehicles
- Einsatzdokumentation: http://localhost:5000/incidents
