from flask import Flask, render_template, request, jsonify
import json
from pathlib import Path

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

DATA_FILE = Path('data/vehicles.json')
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


vehicles = load_vehicles()


@app.route('/')
def index():
    return render_template('monitor.html', title='Alarmmonitor', vehicles=vehicles, status_text=STATUS_TEXT)


@app.route('/dispatch')
def dispatch():
    return render_template('dispatch.html', title='Leitstelle', vehicles=vehicles, status_text=STATUS_TEXT)


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
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 400


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
