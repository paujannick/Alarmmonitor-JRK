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
    first_alarm = app.vehicles['RTW1']['alarm']
    inc = next(i for i in app.incidents if i['id'] == inc_id)
    assert [e for e in inc['log'] if e['unit'] == 'RTW1' and e['status'] == 'alarmiert']

    # re-alert should add another log entry and update alarm timestamp
    time.sleep(0.01)
    client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    inc = next(i for i in app.incidents if i['id'] == inc_id)
    log_entries = [e for e in inc['log'] if e['unit'] == 'RTW1' and e['status'] == 'alarmiert']
    assert len(log_entries) == 2
    assert app.vehicles['RTW1']['alarm'] != first_alarm


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
