import os
import sys
import time
from importlib import reload

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app as app_module
from pager_service import PagerConfig, PagerService, pager_bcd, pager_payload


class ListLogger:
    def __init__(self):
        self.messages = []

    def info(self, *args):
        self.messages.append(("info", args))

    def error(self, *args):
        self.messages.append(("error", args))


def setup_app():
    app = reload(app_module)
    app.save_vehicles = lambda: None
    app.save_incidents = lambda: None
    app.save_announcements = lambda: None
    app.vehicles = {k: v.copy() for k, v in app.DEFAULT_VEHICLES.items()}
    app.incidents = []
    app.announcements = []
    return app, app.app.test_client()


def test_pager_bcd_valid_numbers():
    assert pager_bcd(1) == 0x01
    assert pager_bcd(10) == 0x10
    assert pager_bcd(16) == 0x16
    assert pager_bcd(20) == 0x20
    assert pager_bcd(30) == 0x30


def test_pager_bcd_rejects_invalid_numbers():
    for pager in (0, 31, -1):
        try:
            pager_bcd(pager)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{pager} should be invalid")


def test_pager_payload_bytes():
    assert pager_payload(4) == bytes([0x04, 0x00, 0x92, 0x02])
    assert pager_payload(30) == bytes([0x30, 0x00, 0x92, 0x02])


def test_alert_vehicle_without_pager_does_not_enqueue():
    app, client = setup_app()
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit))
    inc_id = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc'}).get_json()['id']
    response = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    assert response.status_code == 200
    assert enqueued == [(None, 'RTW1')]


def test_alert_vehicle_with_pager_enqueues_background_job():
    app, client = setup_app()
    app.vehicles['RTW1']['pager'] = 4
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit))
    inc_id = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc'}).get_json()['id']
    response = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    assert response.status_code == 200
    assert enqueued == [(4, 'RTW1')]


def test_alert_does_not_wait_for_radio_transmission():
    app, client = setup_app()
    app.vehicles['RTW1']['pager'] = 4

    def slow_enqueue(pager, unit=None):
        return True

    app.pager_service.enqueue = slow_enqueue
    inc_id = client.post('/api/incidents', json={'keyword': 'Test', 'location': 'Loc'}).get_json()['id']
    started = time.perf_counter()
    response = client.post(f'/api/incidents/{inc_id}/alert', json={'units': ['RTW1']})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < 0.5


def test_multiple_pager_jobs_are_processed_sequentially():
    calls = []

    def sender(pager, config):
        calls.append((pager, time.perf_counter()))
        time.sleep(0.02)

    service = PagerService(PagerConfig(enabled=True), ListLogger(), sender=sender)
    service.start()
    try:
        service.enqueue(1, 'RTW1')
        service.enqueue(2, 'RTW2')
        service._queue.join()
    finally:
        service.stop()
    assert [pager for pager, _ in calls] == [1, 2]
    assert calls[1][1] >= calls[0][1]


def test_pager_error_does_not_break_worker():
    calls = []

    def sender(pager, config):
        calls.append(pager)
        if pager == 1:
            raise RuntimeError('pigpiod nicht erreichbar')

    logger = ListLogger()
    service = PagerService(PagerConfig(enabled=True), logger, sender=sender)
    service.start()
    try:
        service.enqueue(1, 'RTW1')
        service.enqueue(2, 'RTW2')
        service._queue.join()
    finally:
        service.stop()
    assert calls == [1, 2]
    assert any(level == 'error' for level, _ in logger.messages)


def test_manual_pager_test_does_not_change_vehicle_status():
    app, client = setup_app()
    app.vehicles['RTW1']['pager'] = 1
    app.vehicles['RTW1']['status'] = 2
    enqueued = []
    app.pager_service.enqueue = lambda pager, unit=None: enqueued.append((pager, unit)) or True
    response = client.post('/api/vehicles/RTW1/pager-test')
    assert response.status_code == 200
    assert response.get_json()['queued'] is True
    assert enqueued == [(1, 'RTW1')]
    assert app.vehicles['RTW1']['status'] == 2
