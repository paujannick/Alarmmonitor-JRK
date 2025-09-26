import os
import sys
import time
from importlib import reload

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import app as app_module


def setup_app():
    app = reload(app_module)
    # prevent file writes during tests
    app.save_vehicles = lambda: None
    app.save_incidents = lambda: None
    # reset in-memory data
    app.vehicles = {k: v.copy() for k, v in app.DEFAULT_VEHICLES.items()}
    app.incidents = []
    return app, app.app.test_client()


def test_realert_same_incident_updates_log_and_vehicle():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc'})
    inc_id = resp.get_json()['id']

    # first alert assigns vehicle
    client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    first_alarm = app.vehicles['RTW1']['alarm_time']
    inc = next(i for i in app.incidents if i['id'] == inc_id)
    assert [e for e in inc['log'] if e['unit'] == 'RTW1' and e['status'] == 'alarmiert']

    # re-alert should add another log entry and update alarm timestamp
    time.sleep(0.01)
    client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    inc = next(i for i in app.incidents if i['id'] == inc_id)
    log_entries = [e for e in inc['log'] if e['unit'] == 'RTW1' and e['status'] == 'alarmiert']
    assert len(log_entries) == 2
    assert app.vehicles['RTW1']['alarm_time'] != first_alarm


def test_alert_skips_vehicle_in_other_active_incident():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'A', 'location': 'LocA'})
    inc_a = resp.get_json()['id']
    client.post(f'/api/incidents/{inc_a}/alert', json={'units': ['RTW1']})

    resp = client.post('/api/incidents', json={'keyword': 'B', 'location': 'LocB'})
    inc_b = resp.get_json()['id']
    client.post(f'/api/incidents/{inc_b}/alert', json={'units': ['RTW1']})

    inc_b_data = next(i for i in app.incidents if i['id'] == inc_b)
    assert 'RTW1' not in inc_b_data['vehicles']
    assert not [e for e in inc_b_data['log'] if e['unit'] == 'RTW1']
    assert app.vehicles['RTW1']['incident_id'] == inc_a


def test_vehicle_status_reset_after_incident_end():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc'})
    inc_id = resp.get_json()['id']

    client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    assert app.vehicles['RTW1']['status'] == 2

    client.post(f'/api/incidents/{inc_id}/end')
    assert app.vehicles['RTW1']['status'] == 1


def test_vehicle_can_be_alerted_again_after_incident_end():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'A', 'location': 'LocA'})
    inc_a = resp.get_json()['id']
    client.post(f'/api/incidents/{inc_a}/alert', json={'units': ['RTW1']})
    client.post(f'/api/incidents/{inc_a}/end')

    resp = client.post('/api/incidents', json={'keyword': 'B', 'location': 'LocB'})
    inc_b = resp.get_json()['id']
    resp = client.post(f'/api/incidents/{inc_b}/alert', json={'units': ['RTW1']})
    data = resp.get_json()
    assert 'RTW1' in data['alerted']
    assert not data['skipped']
    assert app.vehicles['RTW1']['incident_id'] == inc_b
    assert app.vehicles['RTW1']['status'] == 1


def test_vehicle_can_be_alerted_after_removed_from_incident():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'A', 'location': 'LocA'})
    inc_a = resp.get_json()['id']
    client.post(f'/api/incidents/{inc_a}/alert', json={'units': ['RTW1']})
    client.put(f'/api/incidents/{inc_a}', json={'vehicles': []})
    assert app.vehicles['RTW1']['status'] == 1

    resp = client.post('/api/incidents', json={'keyword': 'B', 'location': 'LocB'})
    inc_b = resp.get_json()['id']
    resp = client.post(f'/api/incidents/{inc_b}/alert', json={'units': ['RTW1']})
    data = resp.get_json()
    assert 'RTW1' in data['alerted']
    assert not data['skipped']
    assert app.vehicles['RTW1']['incident_id'] == inc_b
    assert app.vehicles['RTW1']['status'] == 1


def test_alert_handles_legacy_string_location():
    app, client = setup_app()
    app.incidents.append({
        'id': 1,
        'start': '2025-01-01T00:00:00',
        'location': 'Altstadt',
        'vehicles': [],
        'keyword': 'Test',
        'notes': [],
        'log': [],
        'active': True,
        'priority': '',
        'patient': '',
    })

    resp = client.post('/api/incidents/1/alert', json={'units': ['RTW1']})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['alerted'] == ['RTW1']
    assert not data['skipped']
    assert app.vehicles['RTW1']['location'] == 'Altstadt'
