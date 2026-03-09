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


def test_plan_requires_address():
    client = app.test_client()
    resp = client.post('/api/plan', json={})
    assert resp.status_code == 400


def test_plan_returns_structured_plan_and_response():
    client = app.test_client()
    resp = client.post('/api/plan', json={'address': '17825 Woodcrest Dr, Pioneer, CA'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'plan' in data
    assert 'response' in data
    plan = data['plan']
    assert 'request_type' in plan or 'planner_summary' in plan or 'steps' in plan
