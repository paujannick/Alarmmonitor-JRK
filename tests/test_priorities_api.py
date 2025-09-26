import json

import app as app_module


app = app_module.app


def test_priorities_api_roundtrip(tmp_path, monkeypatch):
    priority_file = tmp_path / 'priorities.json'
    monkeypatch.setattr(app_module, 'PRIORITY_FILE', priority_file)
    app_module.priorities.clear()
    app_module.priorities.extend(['R0', 'R1'])

    client = app.test_client()

    res = client.get('/api/priorities')
    assert res.status_code == 200
    assert res.get_json() == ['R0', 'R1']

    payload = {'priorities': [' R2', 'R2', '', None, 'R3']}
    res = client.post('/api/priorities', json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert data['priorities'] == ['R2', 'R3']

    assert priority_file.exists()
    saved = json.loads(priority_file.read_text(encoding='utf-8'))
    assert saved == ['R2', 'R3']

    res = client.post('/api/priorities', json={'priorities': 'invalid'})
    assert res.status_code == 400
    assert app_module.priorities == ['R2', 'R3']
