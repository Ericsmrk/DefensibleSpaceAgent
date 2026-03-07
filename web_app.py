from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, render_template_string, request, Response

from src.agent import run_agent
from src.llm_client import LLMClient
from src.tools import geocode_google

app = Flask(__name__)

# Prompt sent to the OpenAI LLM during the planner step (Run planner button).
PLANNER_PROMPT = (
    'This is a test prompt. print the words "test prompt successfull" and a smiley face.'
)
PLANNER_SYSTEM_FOR_TEST = "You are a helpful assistant. Do exactly what the user asks."

# Google Maps API key: set GOOGLE_MAPS_KEY in .env; use placeholder if not set so UI still loads.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_KEY") or "YOUR_GOOGLE_MAPS_API_KEY"

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ClearSafe — Defensible Space Assessment</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #0d1117;
      --card: #161b22;
      --border: #30363d;
      --text: #e6edf3;
      --text-muted: #8b949e;
      --accent: #f97316;
      --accent-hover: #ea580c;
      --danger: #dc2626;
      --success: #22c55e;
    }
    * { box-sizing: border-box; }
    body {
      font-family: 'DM Sans', -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      max-width: 920px;
      margin: 0 auto;
      padding: 1.5rem 1rem;
      min-height: 100vh;
    }
    h1 { font-size: 1.75rem; font-weight: 700; margin-bottom: 0.2rem; }
    .sub { color: var(--text-muted); font-size: 0.95rem; margin-top: 0; }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-top: 1.25rem;
    }
    .card-title { font-size: 1rem; font-weight: 600; margin: 0 0 0.75rem 0; color: var(--text); }
    .search-wrap {
      position: relative;
      width: 100%;
    }
    .search-input {
      width: 100%;
      padding: 0.85rem 1rem;
      font-size: 1rem;
      font-family: inherit;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--bg);
      color: var(--text);
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .search-input::placeholder { color: var(--text-muted); }
    .search-input:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.2);
    }
    .search-hint { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.5rem; }
    .msg-invalid {
      font-size: 0.875rem;
      color: var(--danger);
      margin-top: 0.5rem;
      min-height: 1.25rem;
    }
    .msg-invalid.hidden { display: none; }
    #map-container {
      width: 100%;
      height: 320px;
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
      margin-top: 1rem;
      background: #1a1f26;
    }
    #map { width: 100%; height: 100%; }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.75rem 1.5rem;
      font-size: 1rem;
      font-weight: 600;
      font-family: inherit;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      transition: background 0.2s, opacity 0.2s;
    }
    .btn-primary {
      background: var(--accent);
      color: #fff;
      margin-top: 1rem;
    }
    .btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
    .btn-primary:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .muted { color: var(--text-muted); }
    textarea {
      width: 100%;
      min-height: 80px;
      font-size: 1rem;
      padding: 0.75rem;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--bg);
      color: var(--text);
      font-family: inherit;
      margin-top: 0.5rem;
    }
    pre { background: var(--bg); padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.85rem; border: 1px solid var(--border); }
    .hidden-fields { display: none; }
  </style>
</head>
<body>
  <h1>ClearSafe</h1>
  <p class="sub">Wildfire defensible-space assessment</p>

  <section class="card" aria-label="Property search">
    <h2 class="card-title">Find your property</h2>
    <p class="muted" style="margin: 0 0 0.75rem 0;">Start typing a US address to search. Select a result to enable fire risk analysis.</p>
    <form id="property-form" action="#" method="post">
      <div class="search-wrap">
        <input type="text" id="address" class="search-input" placeholder="e.g. 17825 Woodcrest Dr, Pioneer, CA" autocomplete="off" aria-label="Property address" />
      </div>
      <p class="search-hint">Suggestions are restricted to addresses in the United States.</p>
      <p id="msg-invalid" class="msg-invalid hidden" role="alert">Select a valid property from the list.</p>
      <div id="map-container">
        <div id="map"></div>
      </div>
      <input type="hidden" id="selected_address" name="selected_address" value="" />
      <input type="hidden" id="selected_lat" name="selected_lat" value="" />
      <input type="hidden" id="selected_lng" name="selected_lng" value="" />
      <button type="button" id="analyze-btn" class="btn btn-primary" disabled>Analyze Fire Risk</button>
      <p class="muted" style="margin: 1rem 0 .5rem 0;">Run the planner (OpenAI) using the address above.</p>
      <button type="button" id="run-plan" class="btn btn-primary">Run planner</button>
      <div id="plan-out" class="card" style="display:none; margin-top: 1rem;"></div>
    </form>
  </section>

  <section class="card" style="margin-top: 1.5rem;">
    <h2 class="card-title">What should we assess?</h2>
    <label for="prompt">Optional notes or focus</label>
    <textarea id="prompt" placeholder="e.g. Focus on vegetation within 30 ft of structures"></textarea>
    <br />
    <button type="button" id="run" class="btn btn-primary">Run Assessment (manual)</button>
  </section>

  <div id="out" class="card" style="display:none; margin-top: 1.5rem;"></div>

  <script src="https://maps.googleapis.com/maps/api/js?key={{ google_maps_api_key }}&libraries=places&callback=initMap" async defer></script>
  <script>
    function escapeHtml(s) {
      const div = document.createElement('div');
      div.textContent = s;
      return div.innerHTML;
    }
    const out = document.getElementById('out');
    const addressInput = document.getElementById('address');
    const msgInvalid = document.getElementById('msg-invalid');
    const analyzeBtn = document.getElementById('analyze-btn');
    const hiddenAddress = document.getElementById('selected_address');
    const hiddenLat = document.getElementById('selected_lat');
    const hiddenLng = document.getElementById('selected_lng');

    // Last confirmed place from Places Autocomplete (formatted address + geometry).
    // If user edits the textbox after selection, we clear this and disable the button.
    let lastSelectedPlace = null;

    function setPlaceValid(place) {
      lastSelectedPlace = place;
      hiddenAddress.value = place.formattedAddress || '';
      hiddenLat.value = place.lat != null ? String(place.lat) : '';
      hiddenLng.value = place.lng != null ? String(place.lng) : '';
      analyzeBtn.disabled = !(place.lat != null && place.lng != null);
      msgInvalid.classList.add('hidden');
    }

    function setPlaceInvalid() {
      lastSelectedPlace = null;
      hiddenAddress.value = '';
      hiddenLat.value = '';
      hiddenLng.value = '';
      analyzeBtn.disabled = true;
      msgInvalid.classList.remove('hidden');
    }

    function syncButtonState() {
      var trimmed = addressInput.value.trim();
      if (!trimmed) {
        analyzeBtn.disabled = true;
        msgInvalid.classList.add('hidden');
        return;
      }
      if (lastSelectedPlace && lastSelectedPlace.formattedAddress === trimmed &&
          lastSelectedPlace.lat != null && lastSelectedPlace.lng != null) {
        analyzeBtn.disabled = false;
        msgInvalid.classList.add('hidden');
        return;
      }
      setPlaceInvalid();
    }

    addressInput.addEventListener('input', syncButtonState);
    addressInput.addEventListener('focus', syncButtonState);

    // Prevent form submit on Enter in the address field (would POST to "/" and get 405).
    document.getElementById('property-form').addEventListener('submit', function(e) {
      e.preventDefault();
    });

    var map = null;
    var marker = null;
    var fallbackCircle = null;

    function initMap() {
      var defaultCenter = { lat: 39.0, lng: -98.0 };
      map = new google.maps.Map(document.getElementById('map'), {
        center: defaultCenter,
        zoom: 4,
        styles: [
          { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
          { featureType: 'transit', stylers: [{ visibility: 'off' }] }
        ],
        mapTypeControl: true,
        streetViewControl: false,
        fullscreenControl: true,
        zoomControl: true
      });

      var autocomplete = new google.maps.places.Autocomplete(addressInput, {
        types: ['address'],
        componentRestrictions: { country: 'us' },
        fields: ['formatted_address', 'geometry', 'name']
      });

      autocomplete.addListener('place_changed', function() {
        var place = autocomplete.getPlace();
        if (!place.geometry || !place.geometry.location) {
          setPlaceInvalid();
          return;
        }
        var lat = place.geometry.location.lat();
        var lng = place.geometry.location.lng();
        var formatted = place.formatted_address || (place.name && place.name + ', ' + place.formatted_address) || addressInput.value.trim();
        addressInput.value = formatted;

        setPlaceValid({ formattedAddress: formatted, lat: lat, lng: lng });

        map.setCenter(place.geometry.location);
        map.setZoom(16);

        if (marker) marker.setMap(null);
        marker = new google.maps.Marker({
          map: map,
          position: place.geometry.location,
          title: formatted
        });

        if (fallbackCircle) fallbackCircle.setMap(null);
        // Parcel boundaries are not provided by Google Maps/Places APIs. We use a circle as a
        // visual fallback for "approximate property area" (e.g. ~0.1 acre). For real parcel
        // boundaries you would need a separate parcel data provider (e.g. county GIS, Regrid, etc.).
        var radiusMeters = 35;
        fallbackCircle = new google.maps.Circle({
          map: map,
          center: place.geometry.location,
          radius: radiusMeters,
          fillColor: '#f97316',
          fillOpacity: 0.15,
          strokeColor: '#f97316',
          strokeOpacity: 0.6,
          strokeWeight: 2
        });
      });
    }

    document.getElementById('analyze-btn').addEventListener('click', async function() {
      var addr = hiddenAddress.value.trim();
      var lat = hiddenLat.value.trim();
      var lng = hiddenLng.value.trim();
      if (!addr || !lat || !lng) return;

      out.style.display = 'block';
      out.innerHTML = '<p class="muted">Running assessment...</p>';

      var payload = {
        request: 'Assess wildfire risk for ' + addr,
        address: addr,
        lat: lat,
        lng: lng
      };
      var promptText = document.getElementById('prompt').value.trim();
      if (promptText) payload.request += '. ' + promptText;

      var r = await fetch('/api/assess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!r.ok) {
        out.innerHTML = '<p>Request failed.</p>';
        return;
      }
      var data = await r.json();
      var ex = data.execution || {};
      out.innerHTML = '<h3>Result</h3>' +
        '<p><b>Address:</b> ' + escapeHtml(ex.address || 'n/a') + '</p>' +
        '<p><b>NDVI:</b> ' + (ex.mean_ndvi != null ? ex.mean_ndvi : 'n/a') + '</p>' +
        '<p><b>Fuel Class:</b> ' + escapeHtml(ex.fuel_class || 'n/a') + '</p>' +
        '<p><b>Recommendation:</b> ' + escapeHtml(data.final_response || '') + '</p>' +
        '<details><summary>Structured JSON</summary><pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre></details>';
    });

    document.getElementById('run-plan').onclick = async function() {
      var address = (hiddenAddress.value || addressInput.value || '').trim();
      if (!address) {
        alert('Please enter or select an address first.');
        return;
      }
      var planOut = document.getElementById('plan-out');
      planOut.style.display = 'block';
      planOut.innerHTML = '<p class="muted">Running planner...</p>';
      var r = await fetch('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: address })
      });
      var data = await r.json();
      if (!r.ok) {
        planOut.innerHTML = '<p>Error: ' + escapeHtml(data.error || 'Planner failed') + '</p>';
        return;
      }
      var plan = data.plan || {};
      var responseText = plan.response;
      planOut.innerHTML = responseText != null
        ? '<h3>Planner response</h3><p>' + escapeHtml(responseText) + '</p><details><summary>JSON</summary><pre>' + escapeHtml(JSON.stringify(data.plan, null, 2)) + '</pre></details>'
        : '<h3>Plan</h3><pre>' + escapeHtml(JSON.stringify(data.plan, null, 2)) + '</pre>';
    };

    document.getElementById('run').onclick = async function() {
      var prompt = document.getElementById('prompt').value.trim();
      if (!prompt) prompt = 'Assess wildfire risk for the selected property.';
      var addr = hiddenAddress.value.trim();
      if (addr) prompt = 'Assess wildfire risk for ' + addr + '. ' + prompt;

      out.style.display = 'block';
      out.innerHTML = '<p class="muted">Running assessment...</p>';

      var r = await fetch('/api/assess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request: prompt,
          address: addr || undefined,
          lat: hiddenLat.value || undefined,
          lng: hiddenLng.value || undefined
        })
      });

      if (!r.ok) {
        out.innerHTML = '<p>Request failed.</p>';
        return;
      }
      var data = await r.json();
      var ex = data.execution || {};
      out.innerHTML = '<h3>Result</h3>' +
        '<p><b>Address:</b> ' + escapeHtml(ex.address || 'n/a') + '</p>' +
        '<p><b>NDVI:</b> ' + (ex.mean_ndvi != null ? ex.mean_ndvi : 'n/a') + '</p>' +
        '<p><b>Fuel Class:</b> ' + escapeHtml(ex.fuel_class || 'n/a') + '</p>' +
        '<p><b>Recommendation:</b> ' + escapeHtml(data.final_response || '') + '</p>' +
        '<details><summary>Structured JSON</summary><pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre></details>';
    };
  </script>
</body>
</html>
"""


@app.get("/")
def home():
    html = render_template_string(INDEX_HTML, google_maps_api_key=GOOGLE_MAPS_API_KEY)
    resp = Response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.post("/api/geocode")
def geocode():
    payload = request.get_json(silent=True) or {}
    address = (payload.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400
    try:
        lat, lon, meta = geocode_google(address)
        if lat is None or lon is None:
            return jsonify({"error": meta.get("status", "Geocoding failed")}), 400
        return jsonify({"lat": lat, "lon": lon, "source": meta.get("source", "unknown")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/plan")
def plan():
    """Run the planner step with the configured prompt (OpenAI). Uses address from request for UI flow."""
    payload = request.get_json(silent=True) or {}
    address = (payload.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400
    try:
        client = LLMClient()
        if not client.is_configured():
            return jsonify({"error": "OPENAI_API_KEY not set"}), 503
        response = client.chat_text(
            PLANNER_SYSTEM_FOR_TEST,
            PLANNER_PROMPT,
            fallback="test prompt successfull :)",
        )
        return jsonify({"plan": {"response": response}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/assess")
def assess():
    payload = request.get_json(silent=True) or {}
    user_request = (payload.get("request") or "").strip()
    if not user_request:
        return jsonify({"error": "request is required"}), 400
    # Optional: payload may include address, lat, lng for the fire risk pipeline.
    # run_agent currently derives address from user_request; you can extend to use
    # payload.get("address"), payload.get("lat"), payload.get("lng") when ready.
    result = run_agent(user_request)
    return jsonify(result)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.get("/version")
def version():
    """Returns a version marker so you can confirm the server is running new code."""
    return jsonify({"version": "with-geocode", "has_geocode_ui": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
