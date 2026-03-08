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
# Use {address} in the string to inject the selected property address.
PLANNER_SYSTEM = (
    'You are the "Baseline Fire Danger Planner" for a California wildfire risk assessment system. '
    'You are the first-stage planning agent in a structured multi-step workflow.'
)

PLANNER_PROMPT = (
    "Your task is to produce a HYBRID planner response for the property address below.\n\n"
    "Address: {address}\n\n"
    "This is the FIRST step of a structured wildfire assessment workflow. "
    "At this stage, you must do three things:\n"
    "1. Briefly define the current assessment scope\n"
    "2. Provide a short preliminary baseline wildfire overview based ONLY on address-level context\n"
    "3. List all possible next steps and prompt the user to issue a request (choose what to do next)\n\n"
    "Important boundaries:\n"
    "- Use ONLY the provided address\n"
    "- Do NOT perform property-level analysis\n"
    "- Do NOT assume anything about the home, structures, defensible space, clearance work, or mitigation status\n"
    "- Do NOT fabricate exact measurements, hazard designations, or parcel-specific facts unless they are directly known\n"
    "- Do NOT provide mitigation advice in this step\n"
    "- Do NOT ask the user for data or clarification; you MAY invite them to issue a request (choose next steps)\n\n"
    "This stage should reflect California-specific wildfire context only, such as:\n"
    "- broad regional wildfire exposure\n"
    "- common vegetation and fuel conditions\n"
    "- terrain and slope context\n"
    "- drought and seasonal dryness\n"
    "- wildland-urban interface exposure\n"
    "- common California fire spread conditions\n"
    "- general CAL FIRE / California wildfire context when appropriate\n\n"
    "Later workflow steps may collect or analyze:\n"
    "- property photos\n"
    "- property coordinates and parcel context\n"
    "- Fire Hazard Severity Zone classification\n"
    "- vegetation and fuel type information\n"
    "- NDVI and vegetation density measurements\n"
    "- slope, aspect, and elevation\n"
    "- distance to dense vegetation or forest edge\n"
    "- recent wildfire perimeter proximity\n"
    "- nearby structure density and ember exposure context\n"
    "- aerial-imagery defensible-space indicators\n"
    "- road access and emergency response context\n"
    "- additional property-level evidence\n\n"
    "If exact data is unavailable, provide a cautious, clearly preliminary baseline based on regional California wildfire context.\n\n"
    "OUTPUT FORMAT (follow exactly):\n\n"
    "Planner Response\n\n"
    "Assessment Mode:\n"
    "Address-level wildfire baseline\n\n"
    "Current Confidence:\n"
    "Preliminary only\n\n"
    "Purpose of This Step:\n"
    "[1-2 sentences explaining that this step provides a general California wildfire baseline using address-level "
    "location context only, and that it is not a full property-level assessment.]\n\n"
    "Initial Baseline Summary:\n"
    "[2-4 sentences describing the general wildfire exposure for the location based only on regional California "
    "wildfire conditions. Keep the wording cautious and preliminary.]\n\n"
    "Likely Baseline Drivers:\n"
    "- [driver]\n"
    "- [driver]\n"
    "- [driver]\n\n"
    "Important Limitation:\n"
    "This result is based only on address-level context and does not yet include property-level analysis or photos, "
    "structure-specific observations, or other property-level evidence.\n\n"
    "Possible Next Steps To Be Done and Included in the Assessment (list each so the user can choose):\n"
    "1. Collect property coordinates and parcel context\n"
    "2. Analyze Fire Hazard Severity Zone classification\n"
    "3. Assess vegetation and fuel type information\n"
    "4. Analyze NDVI and vegetation density measurements\n"
    "5. Assess slope, aspect, and elevation\n"
    "6. Evaluate distance to dense vegetation or forest edge\n"
    "7. Review recent wildfire perimeter proximity\n"
    "8. Assess nearby structure density and ember exposure context\n"
    "9. Review aerial-imagery defensible-space indicators\n"
    "10. Evaluate road access and emergency response context\n"
    "11. Input and then analyze property photos (with a prompt to input the photos) \n"
    "12. Incorporate additional property-level evidence\n\n"
    "Prompt the user:\n"
    "[1-2 sentences inviting the user to issue a request: tell them they can choose one or more of the possible next "
    "steps above, or describe another assessment need, and that their request will guide the next step.]\n\n"
    "Style rules:\n"
    "- Keep the full response concise\n"
    "- Sound professional and structured\n"
    "- Make the planning role explicit\n"
    "- Make all conclusions preliminary\n"
    "- Do not provide defensible-space recommendations yet\n"
    "- Do not mention tool names unless naturally necessary\n"
    "- Do not output JSON\n"
)

# Google Maps API key: set GOOGLE_MAPS_KEY in .env; use placeholder if not set so UI still loads.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_KEY") or "YOUR_GOOGLE_MAPS_API_KEY"

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ClearSafe - Defensible Space Assessment</title>
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
    .planner-response {
      white-space: pre-wrap;
      line-height: 1.6;
      font-size: 0.95rem;
      margin: 0.75rem 0;
      padding: 1rem;
      background: var(--bg);
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .planner-response strong { color: var(--accent); font-weight: 600; }
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

  <section class="card" style="margin-top: 1.5rem;">
    <h2 class="card-title">Quick joke</h2>
    <div class="search-wrap">
      <input type="text" id="joke-input" class="search-input" placeholder="Give me a word to joke about!" aria-label="Joke topic" />
    </div>
    <button type="button" id="joke-btn" class="btn btn-primary" style="margin-top: 0.75rem;">Submit</button>
    <div id="joke-out" class="card" style="display:none; margin-top: 1rem; padding: 1rem;"></div>
  </section>

  <div id="out" class="card" style="display:none; margin-top: 1.5rem;"></div>

  <script>
    function escapeHtml(s) {
      const div = document.createElement('div');
      div.textContent = s;
      return div.innerHTML;
    }
    function formatPlannerResponse(text) {
      try {
        var s = (text != null && typeof text === 'string') ? text : String(text || '');
        var lines = s.split('\\n');
        return lines.map(function(line) {
          var escaped = escapeHtml(line);
          var t = line.trim();
          var isHeader = t.length > 0 && t.length < 60 && t.endsWith(':');
          var isNumbered = t.length > 2 && t.charAt(0) >= '1' && t.charAt(0) <= '9' && t.charAt(1) === '.';
          if (isHeader || isNumbered) return '<strong>' + escaped + '</strong>';
          return escaped;
        }).join('<br>');
      } catch (e) {
        return escapeHtml(String(text || ''));
      }
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

    window.initMap = function initMap() {
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
    };

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
      try {
        planOut.innerHTML = responseText != null
          ? '<h3>Planner response</h3><div class="planner-response">' + formatPlannerResponse(responseText) + '</div><details><summary>JSON</summary><pre>' + escapeHtml(JSON.stringify(data.plan, null, 2)) + '</pre></details>'
          : '<h3>Plan</h3><pre>' + escapeHtml(JSON.stringify(data.plan, null, 2)) + '</pre>';
      } catch (err) {
        planOut.innerHTML = '<h3>Planner response</h3><div class="planner-response">' + escapeHtml(String(responseText != null ? responseText : '')) + '</div><details><summary>JSON</summary><pre>' + escapeHtml(JSON.stringify(data.plan, null, 2)) + '</pre></details>';
      }
    };

    document.getElementById('joke-btn').addEventListener('click', async function() {
      var jokeOut = document.getElementById('joke-out');
      jokeOut.style.display = 'block';
      jokeOut.innerHTML = '<p class="muted">Getting a joke...</p>';
      var word = document.getElementById('joke-input').value.trim();
      var r = await fetch('/api/joke', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word: word })
      });
      var data = await r.json();
      if (!r.ok) {
        jokeOut.innerHTML = '<p class="muted">Error: ' + escapeHtml(data.error || 'Could not get joke') + '</p>';
        return;
      }
      jokeOut.innerHTML = '<p style="margin:0; white-space: pre-wrap;">' + escapeHtml(data.joke || '') + '</p>';
    });

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

    (function loadMaps() {
      var key = {{ google_maps_api_key|tojson }};
      if (!key || key === 'YOUR_GOOGLE_MAPS_API_KEY') return;
      var s = document.createElement('script');
      s.async = true;
      s.defer = true;
      s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key) + '&libraries=places&callback=initMap';
      document.head.appendChild(s);
    })();
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
    """Run the planner step with the built-in prompt (OpenAI). Injects the selected address into the prompt."""
    payload = request.get_json(silent=True) or {}
    address = (payload.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400
    prompt_text = PLANNER_PROMPT.format(address=address)
    try:
        client = LLMClient()
        if not client.is_configured():
            return jsonify({"error": "OPENAI_API_KEY not set"}), 503
        response = client.chat_text(
            PLANNER_SYSTEM,
            prompt_text,
            fallback="Planner could not produce a response.",
        )
        return jsonify({"plan": {"response": response}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


JOKE_SYSTEM = "You tell short, clean, family-friendly jokes. Reply with only the joke text, no preamble or labels."


@app.post("/api/joke")
def joke():
    """Return a small random clean joke from OpenAI, optionally about the given word."""
    payload = request.get_json(silent=True) or {}
    word = (payload.get("word") or "").strip()
    user_prompt = f"Tell me a joke about {word}." if word else "Tell me one random small clean joke."
    try:
        client = LLMClient()
        if not client.is_configured():
            return jsonify({"error": "OPENAI_API_KEY not set"}), 503
        response = client.chat_text(
            JOKE_SYSTEM,
            user_prompt,
            fallback="Why did the scarecrow win an award? He was outstanding in his field!",
        )
        return jsonify({"joke": response.strip()})
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
