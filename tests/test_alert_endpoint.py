import os
import sys
import time
from pathlib import Path
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


def test_alert_after_save_alarms_preassigned_vehicle_once():
    app, client = setup_app()
    app.vehicles['RTW1']['pager'] = 4
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit)) or True
    inc_id = client.post(
        '/api/incidents',
        json={'keyword': 'Test', 'location': 'Loc', 'vehicles': ['RTW1']},
    ).get_json()['id']
    assert app.vehicles['RTW1']['alarm_time'] is None

    response = client.post(f'/api/incidents/{inc_id}/alert', json={'units': []})
    data = response.get_json()

    assert response.status_code == 200
    assert data['alerted'] == ['RTW1']
    assert app.vehicles['RTW1']['alarm_time'] is not None
    assert enqueued == [(4, 'RTW1')]

    response = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    data = response.get_json()
    assert data['alerted'] == []
    assert data['already_alerted'] == ['RTW1']
    assert enqueued == [(4, 'RTW1')]


def test_monitor_registers_gong_end_before_playing_audio():
    monitor_template = Path('templates/monitor.html').read_text(encoding='utf-8')
    play_gong = monitor_template[monitor_template.index('function playGongOnce'):monitor_template.index('function rememberAnnouncementId')]
    play_index = play_gong.index('alarmSound.play()')
    ended_index = play_gong.index('alarmSound.onended = finishWithTimeoutCleanup')
    assert ended_index < play_index
    assert 'playFallbackChime().finally(finishGong)' in monitor_template


def test_realert_requested_unit_only_when_incident_has_existing_vehicles():
    app, client = setup_app()
    app.vehicles['RTW1']['pager'] = 4
    app.vehicles['KTW1']['pager'] = 5
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit)) or True

    inc_id = client.post(
        '/api/incidents',
        json={'keyword': 'Test', 'location': 'Loc', 'vehicles': ['RTW1']},
    ).get_json()['id']

    response = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['KTW1']})
    data = response.get_json()

    assert response.status_code == 200
    assert data['alerted'] == ['KTW1']
    assert data['already_alerted'] == []
    assert app.vehicles['RTW1']['alarm_time'] is None
    assert app.vehicles['KTW1']['alarm_time'] is not None
    assert enqueued == [(5, 'KTW1')]


def test_monitor_groups_new_vehicle_alarms_and_times_out_speech():
    monitor_template = Path('templates/monitor.html').read_text(encoding='utf-8')
    enqueue_alarm = monitor_template[monitor_template.index('function enqueueAlarm'):monitor_template.index('function queueAnnouncement')]
    process_queue = monitor_template[monitor_template.index('function processAlarmQueue'):monitor_template.index('function setLatestIncidentVisible')]
    refresh_function = monitor_template[monitor_template.index('async function refresh'):monitor_template.index('setInterval(() =>')]
    speak_function = monitor_template[monitor_template.index('function speak'):monitor_template.index('function rememberAnnouncementId')]

    assert 'alarmQueue.push(Object.assign({playGong}, item))' in enqueue_alarm
    assert 'playGongOnce()' in process_queue
    assert 'const pendingAlarms = [];' in refresh_function
    assert 'pendingAlarms.push({unit, info, alarmId});' in refresh_function
    assert 'triggerAlarmGroup(pendingAlarms);' in refresh_function
    assert 'synth.cancel();' in speak_function
    assert 'window.setTimeout' in speak_function


def test_monitor_alarms_only_with_explicit_alarm_time():
    monitor_template = Path('templates/monitor.html').read_text(encoding='utf-8')
    compute_alarm_id = monitor_template[monitor_template.index('function computeAlarmId'):monitor_template.index('function renderActiveIncidents')]

    assert 'if (!info || !info.alarm_time) return null;' in compute_alarm_id
    assert 'info.alarm_time || info.incident_id' not in compute_alarm_id


def test_create_incident_with_selected_vehicle_does_not_alert_on_save():
    app, client = setup_app()
    app.vehicles['RTW1']['pager'] = 4
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit)) or True

    response = client.post(
        '/api/incidents',
        json={'keyword': 'Test', 'location': 'Loc', 'vehicles': ['RTW1']},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data['ok']
    assert app.vehicles['RTW1']['incident_id'] == data['id']
    assert app.vehicles['RTW1']['alarm_time'] is None
    assert enqueued == []


def test_update_incident_vehicle_selection_does_not_alert_on_save():
    app, client = setup_app()
    app.vehicles['KTW1']['pager'] = 5
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit)) or True

    inc_id = client.post(
        '/api/incidents',
        json={'keyword': 'Test', 'location': 'Loc', 'vehicles': ['RTW1']},
    ).get_json()['id']

    response = client.put(
        f'/api/incidents/{inc_id}',
        json={'vehicles': ['RTW1', 'KTW1']},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data['ok']
    assert app.vehicles['KTW1']['incident_id'] == inc_id
    assert app.vehicles['KTW1']['alarm_time'] is None
    assert enqueued == []


def test_realert_after_status_clear_uses_incident_log_not_alarm_time():
    app, client = setup_app()
    app.vehicles['RTW1']['pager'] = 4
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit)) or True

    inc_id = client.post(
        '/api/incidents',
        json={'keyword': 'Test', 'location': 'Loc', 'vehicles': ['RTW1']},
    ).get_json()['id']
    client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    assert enqueued == [(4, 'RTW1')]

    # Simulate a vehicle becoming free while the incident history still records
    # that it was already alarmed for this incident.
    app.vehicles['RTW1']['incident_id'] = None
    app.vehicles['RTW1']['alarm_time'] = None

    response = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    data = response.get_json()

    assert response.status_code == 200
    assert data['alerted'] == []
    assert data['already_alerted'] == ['RTW1']
    assert enqueued == [(4, 'RTW1')]
