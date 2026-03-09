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


def test_plan_with_lat_lng_uses_provided_coordinates():
    """Run planner with address + lat/lng (e.g. after Google Places selection) should not require geocoding."""
    client = app.test_client()
    resp = client.post(
        '/api/plan',
        json={
            'address': '17825 Woodcrest Dr, Pioneer, Ca',
            'lat': 38.4655752,
            'lng': -120.5584229,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    plan = data.get('plan') or {}
    loc = plan.get('location_strategy') or {}
    assert loc.get('use_provided_coordinates') is True
    assert loc.get('needs_geocoding') is False
    steps = plan.get('steps') or []
    tool_names = [s.get('tool') for s in steps if isinstance(s, dict)]
    assert 'geocode_google' not in tool_names


def test_assess_passes_address_lat_lng_and_uses_provided_coordinates():
    """When address + lat/lng are sent (e.g. from Google Places), plan uses provided coords and no geocode step."""
    client = app.test_client()
    resp = client.post(
        '/api/assess',
        json={
            'request': 'Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca',
            'address': '17825 Woodcrest Dr, Pioneer, Ca',
            'lat': 38.4655752,
            'lng': -120.5584229,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('validation', {}).get('passed') is True
    ex = data.get('execution') or {}
    assert ex.get('latitude') == 38.4655752
    assert ex.get('longitude') == -120.5584229
    assert ex.get('evidence', {}).get('geocode', {}).get('source') == 'provided'

    # Plan must reflect provided coordinates: no geocoding, no geocode_google step
    plan = data.get('plan') or {}
    loc = plan.get('location_strategy') or {}
    assert loc.get('use_provided_coordinates') is True
    assert loc.get('needs_geocoding') is False
    steps = plan.get('steps') or []
    tool_names = [s.get('tool') for s in steps if isinstance(s, dict)]
    assert 'geocode_google' not in tool_names


def test_assess_accepts_string_lat_lng_from_frontend():
    """Frontend sends lat/lng as strings; backend must parse and use them."""
    client = app.test_client()
    resp = client.post(
        '/api/assess',
        json={
            'request': 'Assess wildfire risk for 123 Main St, City, CA',
            'address': '123 Main St, City, CA',
            'lat': '38.4655752',
            'lng': '-120.5584229',
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('validation', {}).get('passed') is True
    ex = data.get('execution') or {}
    assert ex.get('latitude') == 38.4655752
    assert ex.get('longitude') == -120.5584229
    plan = data.get('plan') or {}
    loc = plan.get('location_strategy') or {}
    assert loc.get('use_provided_coordinates') is True
    assert loc.get('needs_geocoding') is False
