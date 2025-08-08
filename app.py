from flask import Flask, render_template, request, jsonify
import json
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

DATA_FILE = Path('data/vehicles.json')
INCIDENT_FILE = Path('data/incidents.json')
DEFAULT_VEHICLES = {
    'RTW1': {'status': 2, 'note': '', 'location': ''},
    'RTW2': {'status': 2, 'note': '', 'location': ''},
    'KTW1': {'status': 2, 'note': '', 'location': ''},
}

STATUS_TEXT = {
    0: 'außer Dienst',
    1: 'einsatzbereit über Funk',
    2: 'einsatzbereit auf Wache',
    3: 'Einsatz übernommen',
    4: 'Am Einsatzort',
    5: 'Patient aufgenommen',
    6: 'Am Ziel',
}


def load_vehicles():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_VEHICLES.copy()


def save_vehicles():
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(vehicles, f, ensure_ascii=False, indent=2)


def load_incidents():
    if INCIDENT_FILE.exists():
        with open(INCIDENT_FILE, encoding='utf-8') as f:
            return json.load(f)
    return []


def save_incidents():
    INCIDENT_FILE.parent.mkdir(exist_ok=True)
    with open(INCIDENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(incidents, f, ensure_ascii=False, indent=2)


vehicles = load_vehicles()
incidents = load_incidents()


@app.route('/')
def index():
    return render_template('monitor.html', title='Alarmmonitor', vehicles=vehicles, status_text=STATUS_TEXT)


@app.route('/dispatch')
def dispatch():
    return render_template('dispatch.html', title='Leitstelle', vehicles=vehicles, status_text=STATUS_TEXT)


@app.route('/vehicles')
def vehicles_page():
    return render_template('vehicles.html', title='Fahrzeuge', vehicles=vehicles)


@app.route('/incidents')
def incidents_page():
    return render_template('incidents.html', title='Einsätze', incidents=incidents)


@app.route('/api/status')
def api_status():
    return jsonify(vehicles)


@app.route('/api/dispatch', methods=['POST'])
def api_dispatch():
    data = request.json or {}
    unit = data.get('unit')
    status = int(data.get('status', 2))
    note = data.get('note', '')
    location = data.get('location', '')
    if unit in vehicles and status in STATUS_TEXT:
        vehicles[unit]['status'] = status
        vehicles[unit]['note'] = note
        vehicles[unit]['location'] = location
        save_vehicles()
        if status >= 3:
            incident = {
                'id': len(incidents) + 1,
                'time': datetime.utcnow().isoformat(),
                'unit': unit,
                'note': note,
                'location': location,
                'status': status,
            }
            incidents.append(incident)
            save_incidents()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 400


@app.route('/api/vehicles', methods=['POST'])
def api_add_vehicle():
    data = request.json or {}
    unit = data.get('unit')
    if unit and unit not in vehicles:
        vehicles[unit] = {'status': 2, 'note': '', 'location': ''}
        save_vehicles()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 400


@app.route('/api/vehicles/<unit>', methods=['DELETE'])
def api_delete_vehicle(unit):
    if unit in vehicles:
        del vehicles[unit]
        save_vehicles()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
