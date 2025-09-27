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
    app.save_announcements = lambda: None
    # reset in-memory data
    app.vehicles = {k: v.copy() for k, v in app.DEFAULT_VEHICLES.items()}
    app.incidents = []
    app.announcements = []
    return app, app.app.test_client()


def test_realert_same_incident_is_ignored():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc'})
    inc_id = resp.get_json()['id']

    # first alert assigns vehicle
    data_first = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']}).get_json()
    assert data_first['alerted'] == ['RTW1']
    assert not data_first['already_alerted']
    first_alarm = app.vehicles['RTW1']['alarm_time']
    inc = next(i for i in app.incidents if i['id'] == inc_id)
    assert [e for e in inc['log'] if e['unit'] == 'RTW1' and e['status'] == 'alarmiert']

    # re-alert should not duplicate log entries or change timestamps
    time.sleep(0.01)
    data_second = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']}).get_json()
    inc = next(i for i in app.incidents if i['id'] == inc_id)
    log_entries = [e for e in inc['log'] if e['unit'] == 'RTW1' and e['status'] == 'alarmiert']
    assert len(log_entries) == 1
    assert app.vehicles['RTW1']['alarm_time'] == first_alarm
    assert data_second['alerted'] == []
    assert 'RTW1' in data_second['already_alerted']


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


def test_vehicle_priority_is_set_and_cleared():
    app, client = setup_app()
    resp = client.post(
        '/api/incidents',
        json={'keyword': 'Test', 'location': 'Loc', 'priority': 'R1'},
    )
    inc_id = resp.get_json()['id']

    client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    assert app.vehicles['RTW1']['priority'] == 'R1'

    client.post(f'/api/incidents/{inc_id}/end')
    assert app.vehicles['RTW1']['priority'] == ''


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


def test_vehicle_assignment_persists_on_status_change():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc', 'vehicles': ['RTW1']})
    inc_id = resp.get_json()['id']
    assert app.vehicles['RTW1']['incident_id'] == inc_id

    client.post('/api/dispatch', json={'unit': 'RTW1', 'status': 4})
    assert app.vehicles['RTW1']['status'] == 4
    assert app.vehicles['RTW1']['incident_id'] == inc_id

    client.post('/api/dispatch', json={'unit': 'RTW1', 'status': 1})
    assert app.vehicles['RTW1']['incident_id'] is None


def test_remove_vehicle_requires_free_status():
    app, client = setup_app()
    resp = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc', 'vehicles': ['RTW1']})
    inc_id = resp.get_json()['id']
    client.post('/api/dispatch', json={'unit': 'RTW1', 'status': 4})

    response = client.put(f'/api/incidents/{inc_id}', json={'vehicles': []})
    data = response.get_json()
    assert response.status_code == 400
    assert not data['ok']
    assert 'blocked' in data and 'RTW1' in data['blocked']
    assert app.vehicles['RTW1']['incident_id'] == inc_id

    client.post('/api/dispatch', json={'unit': 'RTW1', 'status': 1})
    response = client.put(f'/api/incidents/{inc_id}', json={'vehicles': []})
    assert response.status_code == 200
    assert app.vehicles['RTW1']['incident_id'] is None


def test_create_announcement():
    app, client = setup_app()
    resp = client.post('/api/announcements', json={'text': 'Test Durchsage'})
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['ok']
    assert app.announcements
    entry = app.announcements[-1]
    assert entry['text'] == 'Test Durchsage'
    assert 'id' in entry


def test_legacy_ended_incident_does_not_block_alert():
    app, client = setup_app()
    legacy = {
        'id': 1,
        'start': '2024-01-01T10:00:00',
        'end': '2024-01-01T12:00:00',
        'location': 'Altstadt',
        'vehicles': ['RTW1'],
        'keyword': 'Alt',
        'notes': [],
        'log': [],
        # Legacy entries did not store an explicit "active" flag
    }
    app.incidents.append(app.normalise_incident(legacy))

    resp = client.post('/api/incidents', json={'keyword': 'Neu', 'location': 'Neustadt'})
    inc_id = resp.get_json()['id']

    resp = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    data = resp.get_json()
    assert resp.status_code == 200
    assert data['alerted'] == ['RTW1']
    assert not data['skipped']


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
