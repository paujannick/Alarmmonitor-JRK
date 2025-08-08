from flask import Flask, render_template, request, jsonify, Response, send_file
import json
from pathlib import Path
from datetime import datetime
from urllib import parse, request as urlrequest
from queue import Queue
import logging
import functools

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

LOG_FILE = Path('app.log')
LOG_FILE.touch(exist_ok=True)
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )
)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

DATA_FILE = Path('data/vehicles.json')
INCIDENT_FILE = Path('data/incidents.json')
DEFAULT_VEHICLES = {
    'RTW1': {
        'name': 'Rettungswagen 1',
        'callsign': 'Rotkreuz RTW 1',
        'crew': [],
        'status': 2,
        'note': '',
        'location': '',
        'lat': None,
        'lon': None,
        'icon': None,
    },
    'RTW2': {
        'name': 'Rettungswagen 2',
        'callsign': 'Rotkreuz RTW 2',
        'crew': [],
        'status': 2,
        'note': '',
        'location': '',
        'lat': None,
        'lon': None,
        'icon': None,
    },
    'KTW1': {
        'name': 'Krankentransportwagen 1',
        'callsign': 'Rotkreuz KTW 1',
        'crew': [],
        'status': 2,
        'note': '',
        'location': '',
        'lat': None,
        'lon': None,
        'icon': None,
    },
}

STATUS_TEXT = {
    0: 'prio. Sprechwunsch',
    1: 'Frei auf Funk',
    2: 'Frei auf Wache',
    3: 'Auf Anfahrt',
    4: 'Am Einsatzort',
    5: 'Sprechwunsch',
    6: 'nicht Einsatzbereit',
    7: 'gebunden',
    8: 'Bedingt Einsatzbereit',
    9: 'Fremdanmeldung',
}


def load_vehicles():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding='utf-8') as f:
            data = json.load(f)
            for info in data.values():
                info.setdefault('icon', None)
            return data
    data = DEFAULT_VEHICLES.copy()
    return data


def save_vehicles():
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(vehicles, f, ensure_ascii=False, indent=2)
    notify_change()


def load_incidents():
    if INCIDENT_FILE.exists():
        with open(INCIDENT_FILE, encoding='utf-8') as f:
            return json.load(f)
    return []


def save_incidents():
    INCIDENT_FILE.parent.mkdir(exist_ok=True)
    with open(INCIDENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(incidents, f, ensure_ascii=False, indent=2)
    notify_change()


vehicles = load_vehicles()
incidents = load_incidents()

listeners = []


def notify_change():
    for q in list(listeners):
        q.put('update')


def event_stream():
    q = Queue()
    listeners.append(q)
    try:
        while True:
            data = q.get()
            yield f"data: {data}\n\n"
    finally:
        listeners.remove(q)


@app.route('/events')
def events():
    return Response(event_stream(), mimetype='text/event-stream')


def geocode(address):
    if not address:
        return None, None
    query = parse.urlencode({'q': address, 'format': 'json'})
    url = f"https://nominatim.openstreetmap.org/search?{query}"
    try:
        with urlrequest.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass
    return None, None


@app.route('/')
def index():
    return render_template('monitor.html', title='Alarmmonitor', vehicles=vehicles, status_text=STATUS_TEXT)


@app.route('/dispatch')
def dispatch():
    sorted_incidents = sorted(incidents, key=lambda inc: inc.get('start') or '', reverse=True)
    return render_template(
        'dispatch.html',
        title='Leitstelle',
        vehicles=vehicles,
        status_text=STATUS_TEXT,
        incidents=sorted_incidents,
    )


@app.route('/vehicles')
def vehicles_page():
    return render_template('vehicles.html', title='Fahrzeuge', vehicles=vehicles)


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
    lat = data.get('lat') or None
    lon = data.get('lon') or None
    if unit in vehicles and status in STATUS_TEXT:
        if (lat is None or lon is None) and location:
            lat, lon = geocode(location)
        info = vehicles[unit]
        info['status'] = status
        active = any(
            inc.get('active') and unit in inc.get('vehicles', [])
            for inc in incidents
        )
        if note or location or lat is not None or lon is not None:
            info['note'] = note
            info['location'] = location
            info['lat'] = lat
            info['lon'] = lon
        elif not active:
            info['note'] = ''
            info['location'] = ''
            info['lat'] = None
            info['lon'] = None
        for inc in incidents:
            if inc.get('active') and unit in inc.get('vehicles', []):
                inc.setdefault('log', []).append({
                    'time': datetime.utcnow().isoformat(),
                    'unit': unit,
                    'status': status,
                })
        save_vehicles()
        save_incidents()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 400


@app.route('/api/vehicles', methods=['POST'])
def api_add_vehicle():
    data = request.json or {}
    unit = data.get('unit')
    name = data.get('name', unit)
    callsign = data.get('callsign', '')
    crew = data.get('crew', [])
    if unit and unit not in vehicles:
        vehicles[unit] = {
            'name': name,
            'callsign': callsign,
            'crew': crew,
            'status': 2,
            'note': '',
            'location': '',
            'lat': None,
            'lon': None,
            'icon': None,
        }
        save_vehicles()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 400


@app.route('/api/vehicles/<unit>/icon', methods=['POST'])
def api_upload_icon(unit):
    if unit not in vehicles:
        return jsonify({'ok': False}), 404
    file = request.files.get('icon')
    if not file:
        return jsonify({'ok': False}), 400
    icons_dir = Path('static/icons')
    icons_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename).suffix or '.png'
    filename = f"{unit}{ext}"
    path = icons_dir / filename
    file.save(path)
    vehicles[unit]['icon'] = f"icons/{filename}"
    save_vehicles()
    return jsonify({'ok': True, 'icon': vehicles[unit]['icon']})


@app.route('/api/vehicles/<unit>', methods=['DELETE'])
def api_delete_vehicle(unit):
    if unit in vehicles:
        del vehicles[unit]
        save_vehicles()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/incidents', methods=['GET'])
def api_list_incidents():
    return jsonify(incidents)


@app.route('/api/incidents', methods=['POST'])
def api_create_incident():
    data = request.json or {}
    vehicles_assigned = data.get('vehicles', [])
    keyword = data.get('keyword', '')
    note = data.get('note', '')
    location = data.get('location', '')
    lat = data.get('lat') or None
    lon = data.get('lon') or None
    if (lat is None or lon is None) and location:
        lat, lon = geocode(location)
    incident = {
        'id': len(incidents) + 1,
        'start': datetime.utcnow().isoformat(),
        'end': None,
        'vehicles': vehicles_assigned,
        'keyword': keyword,
        'notes': [],
        'log': [],
        'location': {
            'name': location,
            'lat': lat,
            'lon': lon,
        },
        'active': True,
    }
    if note:
        incident['notes'].append({'time': datetime.utcnow().isoformat(), 'text': note})
    for unit in vehicles_assigned:
        incident['log'].append({'time': datetime.utcnow().isoformat(), 'unit': unit, 'status': 'alarmiert'})
        if unit in vehicles:
            info = vehicles[unit]
            info['note'] = keyword
            info['location'] = location
            info['lat'] = lat
            info['lon'] = lon
    incidents.append(incident)
    save_incidents()
    save_vehicles()
    return jsonify({'ok': True, 'id': incident['id']})


@app.route('/api/incidents/<int:inc_id>/notes', methods=['POST'])
def api_add_note(inc_id):
    data = request.json or {}
    text = data.get('text')
    if text:
        for inc in incidents:
            if inc['id'] == inc_id and inc.get('active'):
                inc['notes'].append({'time': datetime.utcnow().isoformat(), 'text': text})
                save_incidents()
                return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>/end', methods=['POST'])
def api_end_incident(inc_id):
    for inc in incidents:
        if inc['id'] == inc_id and inc.get('active'):
            inc['active'] = False
            inc['end'] = datetime.utcnow().isoformat()
            for unit in inc.get('vehicles', []):
                if unit in vehicles:
                    if not any(
                        other.get('active') and unit in other.get('vehicles', [])
                        for other in incidents
                        if other is not inc
                    ):
                        info = vehicles[unit]
                        info['note'] = ''
                        info['location'] = ''
                        info['lat'] = None
                        info['lon'] = None
            save_vehicles()
            save_incidents()
            return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>', methods=['DELETE'])
def api_delete_incident(inc_id):
    for i, inc in enumerate(incidents):
        if inc['id'] == inc_id:
            incidents.pop(i)
            save_incidents()
            return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>/alert', methods=['POST'])
def api_alert_incident(inc_id):
    data = request.json or {}
    units = data.get('units', [])
    for inc in incidents:
        if inc['id'] == inc_id and inc.get('active'):
            for unit in units:
                if unit not in inc['vehicles']:
                    inc['vehicles'].append(unit)
                    inc.setdefault('log', []).append({
                        'time': datetime.utcnow().isoformat(),
                        'unit': unit,
                        'status': 'alarmiert',
                    })
                    if unit in vehicles:
                        info = vehicles[unit]
                        info['note'] = inc['keyword']
                        info['location'] = inc['location']['name']
                        info['lat'] = inc['location']['lat']
                        info['lon'] = inc['location']['lon']
            save_incidents()
            save_vehicles()
            return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/settings')
def settings():
    return render_template('settings.html', title='Einstellungen')


@app.route('/download-log')
def download_log():
    return send_file(LOG_FILE, as_attachment=True)


def log_request_and_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        app.logger.info('%s %s', request.method, request.path)
        try:
            response = func(*args, **kwargs)
            app.logger.info('Completed %s', func.__name__)
            return response
        except Exception:
            app.logger.exception('Error in %s', func.__name__)
            raise

    return wrapper


for name, func in list(app.view_functions.items()):
    if name != 'static':
        app.view_functions[name] = log_request_and_errors(func)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
