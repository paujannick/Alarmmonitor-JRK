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
TEMPLATE_FILE = Path('data/templates.json')
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
        'tts': '',
        'base': '',
        'alarm_time': None,
        'incident_id': None,
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
        'tts': '',
        'base': '',
        'alarm_time': None,
        'incident_id': None,
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
        'tts': '',
        'base': '',
        'alarm_time': None,
        'incident_id': None,
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
            for unit, info in data.items():
                info.setdefault('name', unit)
                info.setdefault('callsign', unit)
                info.setdefault('crew', [])
                info.setdefault('status', 2)
                info.setdefault('note', '')
                info.setdefault('location', '')
                info.setdefault('lat', None)
                info.setdefault('lon', None)
                info.setdefault('icon', None)
                info.setdefault('tts', '')
                info.setdefault('base', '')
                if 'alarm_time' not in info:
                    info['alarm_time'] = info.pop('alarm', None)
                info.setdefault('incident_id', None)
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
            data = json.load(f)
            for inc in data:
                inc.setdefault('priority', '')
                inc.setdefault('patient', '')
            return data
    return []


def save_incidents():
    INCIDENT_FILE.parent.mkdir(exist_ok=True)
    with open(INCIDENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(incidents, f, ensure_ascii=False, indent=2)
    notify_change()


DEFAULT_TEMPLATES = [
    {
        'id': 'bma',
        'label': 'Brandmeldeanlage',
        'keyword': 'Brandmeldeanlage',
        'priority': 'R1',
    },
    {
        'id': 'vu',
        'label': 'Verkehrsunfall',
        'keyword': 'Verkehrsunfall',
        'priority': 'R1',
    },
    {
        'id': 'rd',
        'label': 'Medizinischer Notfall',
        'keyword': 'Medizinischer Notfall',
        'priority': 'R2',
    },
]


def load_templates():
    if TEMPLATE_FILE.exists():
        with open(TEMPLATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_TEMPLATES.copy()


def save_templates():
    TEMPLATE_FILE.parent.mkdir(exist_ok=True)
    with open(TEMPLATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)
    notify_change()


vehicles = load_vehicles()
incidents = load_incidents()
templates = load_templates()

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
    available = {
        name: info
        for name, info in vehicles.items()
        if info.get('status') in (1, 2)
        and not any(
            inc.get('active') and name in inc.get('vehicles', []) for inc in incidents
        )
    }
    return render_template(
        'dispatch.html',
        title='Leitstelle',
        vehicles=vehicles,
        available=available,
        status_text=STATUS_TEXT,
        incidents=sorted_incidents,
        templates=templates,
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
    note = data.get('note')
    location = data.get('location')
    lat = data.get('lat')
    lon = data.get('lon')
    if unit in vehicles and status in STATUS_TEXT:
        if (lat is None or lon is None) and location:
            lat, lon = geocode(location)
        info = vehicles[unit]
        active_inc = next(
            (
                inc
                for inc in incidents
                if inc.get('active') and unit in inc.get('vehicles', [])
            ),
            None,
        )
        active = active_inc is not None
        if active and status in {1, 2}:
            info['status'] = status
            info['incident_id'] = None
            info['alarm_time'] = None
            info['note'] = ''
            if status == 2:
                info['location'] = info.get('base', '')
                if info['location']:
                    info['lat'], info['lon'] = geocode(info['location'])
                else:
                    info['lat'] = info['lon'] = None
            else:
                info['location'] = ''
                info['lat'] = None
                info['lon'] = None
            if active_inc and unit in active_inc.get('vehicles', []):
                active_inc['vehicles'].remove(unit)
                active_inc.setdefault('log', []).append({
                    'time': datetime.utcnow().isoformat(),
                    'unit': unit,
                    'status': status,
                })
            save_vehicles()
            save_incidents()
            return jsonify({'ok': True})
        info['status'] = status
        if note is not None or location is not None or lat is not None or lon is not None:
            if not active:
                info['incident_id'] = None
            if note is not None:
                info['note'] = note
            if location is not None:
                info['location'] = location
                info['lat'] = lat
                info['lon'] = lon
        elif status == 2 and not active:
            info['incident_id'] = None
            info['note'] = ''
            info['location'] = info.get('base', '')
            if info['location']:
                info['lat'], info['lon'] = geocode(info['location'])
            else:
                info['lat'] = info['lon'] = None
        elif not active:
            info['incident_id'] = None
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
    tts = data.get('tts', '')
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
            'tts': tts,
            'base': '',
            'alarm_time': None,
            'incident_id': None,
        }
        save_vehicles()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 400


@app.route('/api/vehicles/<unit>', methods=['PUT'])
def api_update_vehicle(unit):
    if unit not in vehicles:
        return jsonify({'ok': False}), 404
    data = request.json or {}
    info = vehicles[unit]
    name = data.get('name')
    callsign = data.get('callsign')
    crew = data.get('crew')
    tts = data.get('tts')
    base = data.get('base')
    if name is not None:
        info['name'] = name
    if callsign is not None:
        info['callsign'] = callsign
    if crew is not None:
        info['crew'] = crew
    if tts is not None:
        info['tts'] = tts
    if base is not None:
        info['base'] = base
    save_vehicles()
    return jsonify({'ok': True})


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


@app.route('/api/templates', methods=['GET'])
def api_list_templates():
    return jsonify(templates)


@app.route('/api/templates', methods=['POST'])
def api_save_template():
    data = request.json or {}
    tid = data.get('id')
    if not tid:
        return jsonify({'ok': False}), 400
    existing = next((t for t in templates if t.get('id') == tid), None)
    if existing:
        existing.update({k: v for k, v in data.items() if k in ('label', 'keyword', 'priority')})
    else:
        templates.append({
            'id': tid,
            'label': data.get('label', tid),
            'keyword': data.get('keyword', ''),
            'priority': data.get('priority', ''),
        })
    save_templates()
    return jsonify({'ok': True})


@app.route('/api/templates/<tid>', methods=['DELETE'])
def api_delete_template(tid):
    for i, t in enumerate(templates):
        if t.get('id') == tid:
            templates.pop(i)
            save_templates()
            return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/incidents', methods=['POST'])
def api_create_incident():
    data = request.json or {}
    keyword = data.get('keyword', '')
    note = data.get('note', '')
    location = data.get('location', '')
    lat = data.get('lat') or None
    lon = data.get('lon') or None
    priority = data.get('priority', '')
    patient = data.get('patient', '')
    vehicles_req = data.get('vehicles', [])
    if (lat is None or lon is None) and location:
        lat, lon = geocode(location)
    incident = {
        'id': len(incidents) + 1,
        'start': datetime.utcnow().isoformat(),
        'end': None,
        'vehicles': list(vehicles_req),
        'keyword': keyword,
        'notes': [],
        'log': [],
        'location': {
            'name': location,
            'lat': lat,
            'lon': lon,
        },
        'active': True,
        'priority': priority,
        'patient': patient,
    }
    now = datetime.utcnow().isoformat()
    if note:
        incident['notes'].append({'time': now, 'text': note})
    for unit in vehicles_req:
        incident['log'].append({'time': now, 'unit': unit, 'status': 'zugeteilt'})
    incidents.append(incident)
    save_incidents()
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
                        info['incident_id'] = None
                        info['alarm_time'] = None
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
    """Alert the given units for an active incident.

    Each unit is assigned to the incident and its vehicle entry is updated
    with the incident details. Vehicles are automatically set to status 3,
    indicating they are en route to the scene.
    """
    data = request.json or {}
    units = data.get('units', [])
    for inc in incidents:
        if inc['id'] == inc_id and inc.get('active'):
            for unit in units:
                # Skip vehicles that are already bound to another active incident
                if any(
                    other.get('active') and unit in other.get('vehicles', [])
                    for other in incidents
                    if other is not inc
                ):
                    continue
                # Add the vehicle to this incident if not already present
                if unit not in inc['vehicles']:
                    inc['vehicles'].append(unit)
                now = datetime.utcnow().isoformat()
                # Log the alarm time for the incident
                inc.setdefault('log', []).append({
                    'time': now,
                    'unit': unit,
                    'status': 'alarmiert',
                })
                if unit in vehicles:
                    info = vehicles[unit]
                    # Mark vehicle as en route and store incident details
                    info['status'] = 3
                    info['note'] = inc['keyword']
                    info['location'] = inc['location']['name']
                    info['lat'] = inc['location']['lat']
                    info['lon'] = inc['location']['lon']
                    info['alarm_time'] = now
                    info['incident_id'] = inc_id
            save_incidents()
            save_vehicles()
            return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>', methods=['GET'])
def api_get_incident(inc_id):
    for inc in incidents:
        if inc['id'] == inc_id:
            return jsonify(inc)
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>', methods=['PUT'])
def api_update_incident(inc_id):
    data = request.json or {}
    for inc in incidents:
        if inc['id'] == inc_id:
            keyword = data.get('keyword')
            loc = data.get('location') or {}
            loc_name = loc.get('name') if isinstance(loc, dict) else loc
            priority = data.get('priority')
            patient = data.get('patient')
            note = data.get('note')
            vehicles_req = data.get('vehicles')
            if keyword is not None:
                inc['keyword'] = keyword
            if loc_name is not None:
                inc['location']['name'] = loc_name
                if not inc['location'].get('lat') or not inc['location'].get('lon'):
                    lat, lon = geocode(loc_name)
                    inc['location']['lat'] = lat
                    inc['location']['lon'] = lon
            if priority is not None:
                inc['priority'] = priority
            if patient is not None:
                inc['patient'] = patient
            if vehicles_req is not None:
                old_units = set(inc.get('vehicles', []))
                new_units = set(vehicles_req)
                added = new_units - old_units
                removed = old_units - new_units
                inc['vehicles'] = list(new_units)
                now = datetime.utcnow().isoformat()
                for unit in added:
                    inc.setdefault('log', []).append({
                        'time': now,
                        'unit': unit,
                        'status': 'zugeteilt',
                    })
                for unit in removed:
                    inc.setdefault('log', []).append({
                        'time': now,
                        'unit': unit,
                        'status': 'entfernt',
                    })
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
                            info['incident_id'] = None
                            info['alarm_time'] = None
                save_vehicles()
            if note:
                inc.setdefault('notes', []).append({'time': datetime.utcnow().isoformat(), 'text': note})
            save_incidents()
            return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/settings')
def settings():
    return render_template('settings.html', title='Einstellungen', vehicles=vehicles, templates=templates)


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
