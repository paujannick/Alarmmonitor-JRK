from flask import Flask, render_template, request, jsonify, Response, send_file
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib import parse, request as urlrequest
from queue import Queue, Empty
import logging
import functools
from copy import deepcopy

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False


@app.context_processor
def inject_template_globals():
    host = ''
    try:
        if request.host:
            host = request.host.split(':')[0]
    except RuntimeError:
        host = ''
    return {'app_settings': settings, 'backend_host': host}


def now_local_iso():
    """Return the current local time as ISO 8601 string with timezone info."""

    return datetime.now().astimezone().isoformat()


def to_local_datetime(value):
    """Parse an ISO timestamp and convert it to the local timezone."""

    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def format_local(value, fmt='%d.%m.%Y %H:%M:%S'):
    dt = to_local_datetime(value)
    if not dt:
        return value or ''
    return dt.strftime(fmt)


app.jinja_env.filters['format_local'] = format_local

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
PRIORITY_FILE = Path('data/priorities.json')
ANNOUNCEMENTS_FILE = Path('data/announcements.json')
MAX_ANNOUNCEMENTS = 100
SETTINGS_FILE = Path('data/settings.json')
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
        'priority': '',
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
        'priority': '',
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
        'priority': '',
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


DEFAULT_SETTINGS = {
    'operation_area': {
        'name': 'Lich, Deutschland',
        'lat': 50.517,
        'lon': 8.816,
        'zoom': 13,
    },
    'monitor': {
        'show_weather': True,
    },
    'network': {
        'router_name': 'TP-Link Reise Router',
        'admin_url': 'http://tplinkwifi.net',
        'notes': '',
    },
}


def parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'true', '1', 'yes', 'on'}:
            return True
        if lowered in {'false', '0', 'no', 'off'}:
            return False
    return default


def normalise_router_url(value):
    if not value:
        return ''
    if not isinstance(value, str):
        return ''
    trimmed = value.strip()
    if not trimmed:
        return ''
    parsed = parse.urlparse(trimmed if '://' in trimmed else f'http://{trimmed}')
    scheme = parsed.scheme or 'http'
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ''
    normalised = parse.urlunparse((scheme, netloc, path, '', '', ''))
    return normalised.rstrip('/')


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
    else:
        data = {}
    settings = deepcopy(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        operation_area = data.get('operation_area') or {}
        if isinstance(operation_area, dict):
            merged_area = settings['operation_area'].copy()
            merged_area.update({
                k: v
                for k, v in operation_area.items()
                if k in {'name', 'lat', 'lon', 'zoom'}
            })
            settings['operation_area'] = merged_area
        monitor_settings = data.get('monitor') or {}
        if isinstance(monitor_settings, dict):
            merged_monitor = settings['monitor'].copy()
            if 'show_weather' in monitor_settings:
                merged_monitor['show_weather'] = parse_bool(
                    monitor_settings.get('show_weather'),
                    merged_monitor.get('show_weather', True),
                )
            settings['monitor'] = merged_monitor
        network_settings = data.get('network') or {}
        if isinstance(network_settings, dict):
            merged_network = settings['network'].copy()
            for key in ('router_name', 'admin_url', 'notes'):
                value = network_settings.get(key)
                if isinstance(value, str):
                    merged_network[key] = value.strip()
            settings['network'] = merged_network
    return settings


def save_settings():
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    notify_change()


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
                info.setdefault('priority', '')
            return data
    data = DEFAULT_VEHICLES.copy()
    return data


def save_vehicles():
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(vehicles, f, ensure_ascii=False, indent=2)
    notify_change()


def normalise_incident(incident):
    """Ensure legacy incident entries have the structure newer code expects."""

    loc = incident.get('location')
    if isinstance(loc, dict):
        name = loc.get('name') or ''
        lat = loc.get('lat')
        lon = loc.get('lon')
    else:
        name = loc or ''
        lat = None
        lon = None

    # Fall back to legacy top-level lat/lon fields if the mapping has no coords
    if lat is None:
        lat = incident.get('lat')
    if lon is None:
        lon = incident.get('lon')

    incident['location'] = {'name': name, 'lat': lat, 'lon': lon}
    incident.setdefault('vehicles', [])
    incident.setdefault('notes', [])
    incident.setdefault('log', [])

    active = incident.get('active')
    if isinstance(active, str):
        active = active.strip().lower()
        if active in {'false', '0', 'nein', 'no'}:
            active = False
        elif active in {'true', '1', 'ja', 'yes'}:
            active = True
        else:
            active = None
    if active is None:
        active = not bool(incident.get('end'))
    incident['active'] = bool(active)

    incident.setdefault('priority', '')
    incident.setdefault('patient', '')
    return incident


def load_incidents():
    if INCIDENT_FILE.exists():
        with open(INCIDENT_FILE, encoding='utf-8') as f:
            data = json.load(f)
            return [normalise_incident(inc) for inc in data]
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

DEFAULT_PRIORITIES = ['R0', 'R1', 'R2', 'R3']


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


def load_priorities():
    if PRIORITY_FILE.exists():
        with open(PRIORITY_FILE, encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                cleaned = []
                seen = set()
                for item in data:
                    if item is None:
                        continue
                    value = str(item).strip()
                    if not value or value in seen:
                        continue
                    cleaned.append(value)
                    seen.add(value)
                return cleaned
            elif isinstance(data, dict):
                # Support legacy dict-based storage where priorities
                # were stored as mapping keys or under a 'priorities' field.
                items = data.get('priorities') if 'priorities' in data else data.keys()
                cleaned = []
                seen = set()
                for item in items:
                    if item is None:
                        continue
                    value = str(item).strip()
                    if not value or value in seen:
                        continue
                    cleaned.append(value)
                    seen.add(value)
                return cleaned
    return DEFAULT_PRIORITIES.copy()


def save_priorities():
    PRIORITY_FILE.parent.mkdir(exist_ok=True)
    with open(PRIORITY_FILE, 'w', encoding='utf-8') as f:
        json.dump(priorities, f, ensure_ascii=False, indent=2)
    notify_change()


def load_announcements():
    if ANNOUNCEMENTS_FILE.exists():
        try:
            with open(ANNOUNCEMENTS_FILE, encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    cleaned = []
                    for entry in data:
                        if not isinstance(entry, dict):
                            continue
                        text = (entry.get('text') or '').strip()
                        if not text:
                            continue
                        cleaned.append(
                            {
                                'id': entry.get('id') or 0,
                                'time': entry.get('time') or now_local_iso(),
                                'text': text,
                            }
                        )
                    return cleaned
        except json.JSONDecodeError:
            pass
    return []


def save_announcements():
    ANNOUNCEMENTS_FILE.parent.mkdir(exist_ok=True)
    with open(ANNOUNCEMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(announcements, f, ensure_ascii=False, indent=2)
    notify_change()


def update_vehicle_incident_details(unit, incident, *, newly_assigned=False):
    info = vehicles.get(unit)
    if not info or not incident:
        return
    incident = normalise_incident(dict(incident))
    info['incident_id'] = incident.get('id')
    info['note'] = incident.get('keyword') or ''
    loc = incident.get('location') or {}
    info['location'] = loc.get('name') or ''
    info['lat'] = loc.get('lat')
    info['lon'] = loc.get('lon')
    info['priority'] = incident.get('priority') or ''
    if newly_assigned:
        info['alarm_time'] = None


vehicles = load_vehicles()
incidents = load_incidents()
templates = load_templates()
priorities = load_priorities()
announcements = load_announcements()
settings = load_settings()

listeners = []
weather_cache = {'data': None, 'expires': None}


def notify_change():
    for q in list(listeners):
        q.put('update')


def finalise_incident_if_clear(incident):
    """Check whether an incident has any bound vehicles without ending it.

    Incidents previously ended automatically once every assigned vehicle was
    back in status 1 or 2. This implicit behaviour hid the "Einsatz beenden"
    button after a save operation because the incident switched to inactive.
    The function now simply reports whether all assigned vehicles are free and
    leaves the incident active so that it can be closed explicitly via the UI.
    """

    if not incident or not incident.get('active'):
        return False
    incident = normalise_incident(incident)
    return all(
        (vehicles.get(unit) or {}).get('status', 2) in (1, 2)
        for unit in incident.get('vehicles', [])
    )


def event_stream():
    q = Queue()
    listeners.append(q)
    try:
        while True:
            try:
                data = q.get(timeout=15)
            except Empty:
                yield ': keepalive\n\n'
                continue
            yield f"data: {data}\n\n"
    finally:
        try:
            listeners.remove(q)
        except ValueError:
            pass


@app.route('/events')
def events():
    return Response(event_stream(), mimetype='text/event-stream')


def geocode(address):
    if not address:
        return None, None
    query = parse.urlencode({'q': address, 'format': 'json'})
    url = f"https://nominatim.openstreetmap.org/search?{query}"
    try:
        req = urlrequest.Request(url, headers={'User-Agent': 'Alarmmonitor/1.0'})
        with urlrequest.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass
    return None, None


def reverse_geocode(lat, lon):
    if lat is None or lon is None:
        return None
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    query = parse.urlencode(
        {
            'lat': lat,
            'lon': lon,
            'format': 'jsonv2',
            'accept-language': 'de',
        }
    )
    url = f"https://nominatim.openstreetmap.org/reverse?{query}"
    try:
        req = urlrequest.Request(url, headers={'User-Agent': 'Alarmmonitor/1.0'})
        with urlrequest.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, dict):
                display = data.get('display_name')
                if display:
                    return display
    except Exception:
        pass
    return None


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
    priority_options = list(priorities)
    for source in (incidents, templates):
        for entry in source:
            value = entry.get('priority') if isinstance(entry, dict) else None
            if value and value not in priority_options:
                priority_options.append(value)
    return render_template(
        'dispatch.html',
        title='Leitstelle',
        vehicles=vehicles,
        available=available,
        status_text=STATUS_TEXT,
        incidents=sorted_incidents,
        templates=templates,
        priorities=priorities,
        priority_options=priority_options,
    )


@app.route('/vehicles')
def vehicles_page():
    return render_template(
        'vehicles.html',
        title='Fahrzeuge',
        vehicles=vehicles,
        status_text=STATUS_TEXT,
    )


@app.route('/vehicle-status')
def vehicle_status_page():
    return render_template(
        'vehicle_status.html',
        title='Fahrzeugstatus',
        vehicles=vehicles,
        status_text=STATUS_TEXT,
    )


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
            info['priority'] = ''
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
            incident_cleared = False
            if active_inc and unit in active_inc.get('vehicles', []):
                active_inc['vehicles'].remove(unit)
                active_inc.setdefault('log', []).append({
                    'time': now_local_iso(),
                    'unit': unit,
                    'status': status,
                })
                incident_cleared = finalise_incident_if_clear(active_inc)
            save_vehicles()
            save_incidents()
            ended = bool(active_inc and not active_inc.get('active'))
            response = {'ok': True, 'incidentEnded': ended}
            if incident_cleared and not ended:
                response['incidentClear'] = True
            return jsonify(response)
        info['status'] = status
        if note is not None or location is not None or lat is not None or lon is not None:
            if not active:
                info['incident_id'] = None
                info['priority'] = ''
            if note is not None:
                info['note'] = note
            if location is not None:
                info['location'] = location
                info['lat'] = lat
                info['lon'] = lon
        elif status == 2 and not active:
            info['incident_id'] = None
            info['note'] = ''
            info['priority'] = ''
            info['location'] = info.get('base', '')
            if info['location']:
                info['lat'], info['lon'] = geocode(info['location'])
            else:
                info['lat'] = info['lon'] = None
        elif not active:
            info['incident_id'] = None
            info['note'] = ''
            info['priority'] = ''
            info['location'] = ''
            info['lat'] = None
            info['lon'] = None
        for inc in incidents:
            if inc.get('active') and unit in inc.get('vehicles', []):
                inc.setdefault('log', []).append({
                    'time': now_local_iso(),
                    'unit': unit,
                    'status': status,
                })
                finalise_incident_if_clear(inc)
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
            'priority': '',
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


def _normalise_priorities(items):
    cleaned = []
    seen = set()
    for item in items:
        if item is None:
            continue
        value = str(item).strip()
        if not value or value in seen:
            continue
        cleaned.append(value)
        seen.add(value)
    return cleaned


@app.route('/api/priorities', methods=['GET'])
def api_list_priorities():
    return jsonify(priorities)


@app.route('/api/priorities', methods=['POST'])
def api_save_priorities():
    data = request.json or {}
    items = data.get('priorities')
    if not isinstance(items, list):
        return jsonify({'ok': False, 'error': 'invalid'}), 400
    cleaned = _normalise_priorities(items)
    priorities[:] = cleaned
    save_priorities()
    return jsonify({'ok': True, 'priorities': priorities})


@app.route('/api/announcements', methods=['GET'])
def api_list_announcements():
    return jsonify(announcements)


@app.route('/api/announcements', methods=['POST'])
def api_create_announcement():
    data = request.json or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'Text erforderlich'}), 400
    entry = {
        'id': int(datetime.now().timestamp() * 1000),
        'time': now_local_iso(),
        'text': text,
    }
    announcements.append(entry)
    if len(announcements) > MAX_ANNOUNCEMENTS:
        announcements[:] = announcements[-MAX_ANNOUNCEMENTS:]
    save_announcements()
    return jsonify({'ok': True, 'announcement': entry})


@app.route('/api/incidents', methods=['POST'])
def api_create_incident():
    data = request.json or {}
    keyword = data.get('keyword', '')
    note = data.get('note', '')
    location_raw = data.get('location', '')
    lat = data.get('lat')
    lon = data.get('lon')
    if isinstance(location_raw, dict):
        location = location_raw.get('name', '')
        lat = location_raw.get('lat', lat)
        lon = location_raw.get('lon', lon)
    else:
        location = location_raw
    location = (location or '').strip()
    try:
        lat = float(lat)
    except (TypeError, ValueError):
        lat = None
    try:
        lon = float(lon)
    except (TypeError, ValueError):
        lon = None
    priority = data.get('priority', '')
    patient = data.get('patient', '')
    vehicles_req = data.get('vehicles', [])
    if (lat is None or lon is None) and location:
        lat, lon = geocode(location)
    incident = {
        'id': len(incidents) + 1,
        'start': now_local_iso(),
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
    now = now_local_iso()
    if note:
        incident['notes'].append({'time': now, 'text': note})
    for unit in vehicles_req:
        incident['log'].append({'time': now, 'unit': unit, 'status': 'zugeteilt'})
    incidents.append(incident)
    if vehicles_req:
        for unit in vehicles_req:
            update_vehicle_incident_details(unit, incident, newly_assigned=True)
        save_vehicles()
    save_incidents()
    return jsonify({'ok': True, 'id': incident['id']})


@app.route('/api/incidents/<int:inc_id>/notes', methods=['POST'])
def api_add_note(inc_id):
    data = request.json or {}
    text = data.get('text')
    if text:
        for inc in incidents:
            if inc['id'] == inc_id and inc.get('active'):
                inc['notes'].append({'time': now_local_iso(), 'text': text})
                save_incidents()
                return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>/end', methods=['POST'])
def api_end_incident(inc_id):
    for inc in incidents:
        if inc['id'] == inc_id and inc.get('active'):
            inc['active'] = False
            inc['end'] = now_local_iso()
            for unit in inc.get('vehicles', []):
                if unit in vehicles:
                    if not any(
                        other.get('active') and unit in other.get('vehicles', [])
                        for other in incidents
                        if other is not inc
                    ):
                        info = vehicles[unit]
                        info['status'] = 1
                        info['note'] = ''
                        info['priority'] = ''
                        info['incident_id'] = None
                        info['alarm_time'] = None
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
    """Alert the given units for an active incident.

    Each unit is assigned to the incident and its vehicle entry is updated
    with the incident details. Vehicles retain their current status and are
    not automatically set to status 3. The response additionally reports which
    units were alerted and which were skipped because they were already bound
    to another active incident.
    """
    data = request.json or {}
    units = data.get('units', [])
    for inc in incidents:
        if inc['id'] == inc_id and inc.get('active'):
            inc = normalise_incident(inc)
            alerted = []
            skipped = []
            already = []
            for unit in units:
                # Skip vehicles that are already bound to another active incident
                if any(
                    other.get('active') and unit in other.get('vehicles', [])
                    for other in incidents
                    if other is not inc
                ):
                    skipped.append(unit)
                    continue
                info = vehicles.get(unit)
                already_assigned = unit in inc['vehicles']
                already_active = (
                    already_assigned
                    and info is not None
                    and info.get('incident_id') == inc_id
                )
                if already_active:
                    already.append(unit)
                    continue
                # Add the vehicle to this incident if not already present
                if not already_assigned:
                    inc['vehicles'].append(unit)
                now = now_local_iso()
                # Log the alarm time for the incident
                inc.setdefault('log', []).append({
                    'time': now,
                    'unit': unit,
                    'status': 'alarmiert',
                })
                if unit in vehicles:
                    info = vehicles[unit]
                    # Store incident details without changing vehicle status
                    info['note'] = inc['keyword']
                    info['location'] = inc['location']['name']
                    info['lat'] = inc['location']['lat']
                    info['lon'] = inc['location']['lon']
                    info['alarm_time'] = now
                    info['incident_id'] = inc_id
                    info['priority'] = inc.get('priority', '')
                alerted.append(unit)
            save_incidents()
            save_vehicles()
            return jsonify(
                {
                    'ok': True,
                    'alerted': alerted,
                    'skipped': skipped,
                    'already_alerted': already,
                }
            )
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>', methods=['GET'])
def api_get_incident(inc_id):
    for inc in incidents:
        if inc['id'] == inc_id:
            return jsonify(normalise_incident(inc))
    return jsonify({'ok': False}), 404


@app.route('/api/incidents/<int:inc_id>', methods=['PUT'])
def api_update_incident(inc_id):
    data = request.json or {}
    for inc in incidents:
        if inc['id'] == inc_id:
            inc = normalise_incident(inc)
            keyword = data.get('keyword')
            location_raw = data.get('location')
            priority = data.get('priority')
            patient = data.get('patient')
            note = data.get('note')
            vehicles_req = data.get('vehicles')
            lat_value = data.get('lat')
            lon_value = data.get('lon')
            if isinstance(location_raw, dict):
                loc_name = location_raw.get('name')
                if lat_value is None:
                    lat_value = location_raw.get('lat')
                if lon_value is None:
                    lon_value = location_raw.get('lon')
            else:
                loc_name = location_raw
            if loc_name is not None:
                loc_name = (loc_name or '').strip()
            if keyword is not None:
                inc['keyword'] = keyword
            if loc_name is not None:
                inc['location']['name'] = loc_name
                if loc_name == '':
                    inc['location']['lat'] = None
                    inc['location']['lon'] = None
            try:
                lat_value = float(lat_value)
            except (TypeError, ValueError):
                lat_value = None
            try:
                lon_value = float(lon_value)
            except (TypeError, ValueError):
                lon_value = None
            if lat_value is not None:
                inc['location']['lat'] = lat_value
            if lon_value is not None:
                inc['location']['lon'] = lon_value
            if loc_name:
                lat = inc['location'].get('lat')
                lon = inc['location'].get('lon')
                if lat is None or lon is None:
                    lat, lon = geocode(loc_name)
                    inc['location']['lat'] = lat
                    inc['location']['lon'] = lon
            if priority is not None:
                inc['priority'] = priority
            if patient is not None:
                inc['patient'] = patient
            vehicles_updated = False
            removal_error = None
            if vehicles_req is not None:
                existing_units = list(inc.get('vehicles', []))
                existing_set = set(existing_units)
                requested_units = list(dict.fromkeys(vehicles_req))
                requested_set = set(requested_units)
                added = [unit for unit in requested_units if unit not in existing_set]
                removed = [unit for unit in existing_units if unit not in requested_set]
                blocked = []
                allowed_removed = []
                for unit in removed:
                    info = vehicles.get(unit)
                    status = info.get('status') if info else None
                    if not inc.get('active') or status in {1, 2}:
                        allowed_removed.append(unit)
                    else:
                        blocked.append(unit)
                final_units = requested_units[:]
                for unit in blocked:
                    if unit not in final_units:
                        final_units.append(unit)
                inc['vehicles'] = final_units
                now = now_local_iso()
                for unit in added:
                    inc.setdefault('log', []).append({
                        'time': now,
                        'unit': unit,
                        'status': 'zugeteilt',
                    })
                for unit in allowed_removed:
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
                            info['status'] = 1
                            info['note'] = ''
                            info['incident_id'] = None
                            info['alarm_time'] = None
                            info['location'] = ''
                            info['lat'] = None
                            info['lon'] = None
                            info['priority'] = ''
                for unit in inc.get('vehicles', []):
                    update_vehicle_incident_details(
                        unit,
                        inc,
                        newly_assigned=unit in added,
                    )
                save_vehicles()
                vehicles_updated = True
                finalise_incident_if_clear(inc)
                if blocked:
                    removal_error = {
                        'ok': False,
                        'error': 'Fahrzeuge können nur in Status 1 oder 2 entfernt werden.',
                        'blocked': blocked,
                    }
            if not vehicles_updated and inc.get('vehicles'):
                for unit in inc.get('vehicles', []):
                    update_vehicle_incident_details(unit, inc)
                save_vehicles()
                vehicles_updated = True
            if note:
                inc.setdefault('notes', []).append({'time': now_local_iso(), 'text': note})
            save_incidents()
            if removal_error:
                return jsonify(removal_error), 400
            return jsonify({'ok': True})
    return jsonify({'ok': False}), 404


@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify(settings)


@app.route('/api/settings/operation-area', methods=['PUT'])
def api_update_operation_area():
    data = request.json or {}
    operation_area = dict(settings.get('operation_area') or {})
    name = (data.get('name') or '').strip()
    lat = data.get('lat')
    lon = data.get('lon')
    zoom_value = data.get('zoom', operation_area.get('zoom', 13))
    try:
        zoom = int(float(zoom_value))
    except (TypeError, ValueError):
        zoom = operation_area.get('zoom', 13)
    zoom = max(3, min(18, zoom))
    if lat is None and lon is None and not name:
        return jsonify({'ok': False, 'error': 'Einsatzbereich erfordert einen Namen oder Koordinaten.'}), 400
    try:
        lat = float(lat) if lat is not None else None
    except (TypeError, ValueError):
        lat = None
    try:
        lon = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lon = None
    if (lat is None or lon is None) and name:
        lat, lon = geocode(name)
    if lat is None or lon is None:
        return jsonify({'ok': False, 'error': 'Ort konnte nicht gefunden werden.'}), 400
    if not name:
        display = reverse_geocode(lat, lon)
        if display:
            name = display
        else:
            name = f"{lat:.5f}, {lon:.5f}"
    operation_area.update({'name': name, 'lat': lat, 'lon': lon, 'zoom': zoom})
    settings['operation_area'] = operation_area
    weather_cache['data'] = None
    weather_cache['expires'] = None
    save_settings()
    return jsonify({'ok': True, 'operation_area': operation_area})


@app.route('/api/settings/monitor', methods=['PUT'])
def api_update_monitor_settings():
    data = request.json or {}
    monitor_settings = dict(settings.get('monitor') or {})
    if 'show_weather' not in data:
        return jsonify({'ok': False, 'error': 'Keine gültigen Monitor-Einstellungen übermittelt.'}), 400
    monitor_settings['show_weather'] = parse_bool(
        data.get('show_weather'),
        monitor_settings.get('show_weather', True),
    )
    settings['monitor'] = monitor_settings
    save_settings()
    return jsonify({'ok': True, 'monitor': monitor_settings})


@app.route('/api/settings/network', methods=['PUT'])
def api_update_network_settings():
    data = request.json or {}
    network_settings = dict(settings.get('network') or {})
    router_name = data.get('router_name')
    notes = data.get('notes')
    admin_url = data.get('admin_url')
    if isinstance(router_name, str):
        fallback = DEFAULT_SETTINGS['network']['router_name']
        network_settings['router_name'] = router_name.strip() or fallback
    if isinstance(notes, str):
        network_settings['notes'] = notes.strip()
    url_value = normalise_router_url(admin_url) if admin_url else ''
    if not url_value:
        url_value = DEFAULT_SETTINGS['network']['admin_url']
    network_settings['admin_url'] = url_value
    settings['network'] = network_settings
    save_settings()
    return jsonify({'ok': True, 'network': network_settings})


@app.route('/api/geocode/reverse')
def api_reverse_geocode():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    try:
        lat_value = float(lat)
        lon_value = float(lon)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Ungültige Koordinaten.'}), 400
    address = reverse_geocode(lat_value, lon_value)
    if not address:
        return jsonify({'ok': False, 'error': 'Adresse wurde nicht gefunden.'}), 404
    return jsonify({'ok': True, 'address': address, 'lat': lat_value, 'lon': lon_value})


@app.route('/api/weather')
def api_weather():
    operation_area = settings.get('operation_area') or {}
    lat = operation_area.get('lat')
    lon = operation_area.get('lon')
    if lat is None or lon is None:
        return jsonify({'ok': False, 'error': 'Kein Einsatzbereich konfiguriert.'}), 400
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Ungültige Einsatzbereich-Koordinaten.'}), 400
    now = datetime.now(timezone.utc)
    cache = weather_cache
    if cache['data'] and cache['expires'] and cache['expires'] > now:
        return jsonify(cache['data'])
    query = parse.urlencode(
        {
            'latitude': lat,
            'longitude': lon,
            'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code',
            'timezone': 'auto',
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{query}"
    try:
        req = urlrequest.Request(url, headers={'User-Agent': 'Alarmmonitor/1.0'})
        with urlrequest.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return jsonify({'ok': False, 'error': 'Wetterdienst nicht erreichbar.'}), 502
    current = data.get('current_weather') or data.get('current') or {}
    payload = {
        'ok': True,
        'operation_area': {
            'name': operation_area.get('name', ''),
            'lat': lat,
            'lon': lon,
            'zoom': operation_area.get('zoom', 13),
        },
        'current': {
            'time': current.get('time'),
            'temperature': current.get('temperature') or current.get('temperature_2m'),
            'humidity': current.get('relative_humidity_2m'),
            'wind_speed': current.get('windspeed') or current.get('wind_speed_10m'),
            'weather_code': current.get('weathercode') or current.get('weather_code'),
        },
    }
    cache['data'] = payload
    cache['expires'] = now + timedelta(minutes=5)
    return jsonify(payload)


@app.route('/settings', endpoint='settings')
def settings_page():
    return render_template(
        'settings.html',
        title='Einstellungen',
        vehicles=vehicles,
        templates=templates,
        priorities=priorities,
    )


@app.route('/download-log')
def download_log():
    return send_file(LOG_FILE, as_attachment=True)


@app.route('/api/health')
def api_health():
    return jsonify({'ok': True, 'time': now_local_iso()})


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
