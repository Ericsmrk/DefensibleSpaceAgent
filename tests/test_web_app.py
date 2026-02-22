from web_app import app


def test_healthz():
    client = app.test_client()
    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert resp.get_json() == {'ok': True}


def test_assess_requires_request():
    client = app.test_client()
    resp = client.post('/api/assess', json={})
    assert resp.status_code == 400


def test_assess_success_shape():
    client = app.test_client()
    resp = client.post('/api/assess', json={'request': 'Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'execution' in data
    assert 'final_response' in data
