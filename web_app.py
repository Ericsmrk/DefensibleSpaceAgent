from __future__ import annotations

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

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ClearSafe — Defensible Space Assessment</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; }
    h1 { margin-bottom: .2rem; }
    .sub { color: #555; margin-top: 0; }
    textarea { width: 100%; min-height: 90px; font-size: 1rem; }
    button { margin-top: .7rem; padding: .6rem 1rem; cursor: pointer; }
    .card { margin-top: 1rem; padding: 1rem; border: 1px solid #ddd; border-radius: 8px; }
    .geocode-section { background: #f0f8ff; border: 1px solid #b8d4e8; border-radius: 8px; padding: 1.25rem; margin-top: 1rem; }
    .muted { color: #666; }
    pre { background: #f6f6f6; padding: .8rem; overflow-x: auto; }
  </style>
</head>
<body>
  <h1>ClearSafe</h1>
  <p class="sub">Wildfire defensible-space assistant</p>

  <section class="geocode-section" aria-label="Geocode address to coordinates">
    <h2 style="margin-top: 0;">Get coordinates from address</h2>
    <p class="muted" style="margin: .5rem 0;">Enter an address to get latitude and longitude (geocoding).</p>
    <label for="address">Address</label>
    <input type="text" id="address" placeholder="e.g. 17825 Woodcrest Dr, Pioneer, CA" style="width: 100%; padding: .5rem; font-size: 1rem; margin-top: .3rem; box-sizing: border-box;" />
    <br />
    <button id="geocode">Get lat/long</button>
    <div id="geocode-out" class="card" style="display:none;"></div>
    <p class="muted" style="margin: 1rem 0 .5rem 0;">Run the planner (OpenAI) using the address above.</p>
    <button id="run-plan">Run planner</button>
    <div id="plan-out" class="card" style="display:none;"></div>
  </section>

  <h2 style="margin-top: 2rem;">What should we assess?</h2>
  <label for="prompt">What should we assess?</label>
  <textarea id="prompt" placeholder="Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca"></textarea>
  <br />
  <button id="run">Run Assessment</button>

  <div id="out" class="card" style="display:none;"></div>

  <script>
    function escapeHtml(s) {
      const div = document.createElement('div');
      div.textContent = s;
      return div.innerHTML;
    }
    const out = document.getElementById('out');
    const geocodeOut = document.getElementById('geocode-out');

    document.getElementById('geocode').onclick = async () => {
      const address = document.getElementById('address').value.trim();
      if (!address) return alert('Please enter an address.');

      geocodeOut.style.display = 'block';
      geocodeOut.innerHTML = '<p class="muted">Geocoding...</p>';

      const r = await fetch('/api/geocode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({address: address})
      });

      const data = await r.json();
      if (!r.ok) {
        geocodeOut.innerHTML = '<p>Error: ' + (data.error || 'Geocoding failed') + '</p>';
        return;
      }

      if (data.lat != null && data.lon != null) {
        geocodeOut.innerHTML = `
          <h3>Coordinates</h3>
          <p><b>Latitude:</b> ${data.lat}</p>
          <p><b>Longitude:</b> ${data.lon}</p>
          <p class="muted">Source: ${data.source || 'n/a'}</p>
        `;
      } else {
        geocodeOut.innerHTML = '<p>Could not find coordinates for this address.</p>';
      }
    };

    document.getElementById('run-plan').onclick = async () => {
      const address = document.getElementById('address').value.trim();
      if (!address) return alert('Please enter an address first.');

      const planOut = document.getElementById('plan-out');
      planOut.style.display = 'block';
      planOut.innerHTML = '<p class="muted">Running planner...</p>';

      const r = await fetch('/api/plan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({address: address})
      });

      const data = await r.json();
      if (!r.ok) {
        planOut.innerHTML = '<p>Error: ' + (data.error || 'Planner failed') + '</p>';
        return;
      }
      const plan = data.plan || {};
      const responseText = plan.response;
      planOut.innerHTML = responseText != null
        ? `<h3>Planner response</h3><p>${escapeHtml(responseText)}</p><details><summary>JSON</summary><pre>${JSON.stringify(data.plan, null, 2)}</pre></details>`
        : `<h3>Plan</h3><pre>${JSON.stringify(data.plan, null, 2)}</pre>`;
    };

    document.getElementById('run').onclick = async () => {
      const prompt = document.getElementById('prompt').value.trim();
      if (!prompt) return alert('Please enter a request.');

      out.style.display = 'block';
      out.innerHTML = '<p class="muted">Running assessment...</p>';

      const r = await fetch('/api/assess', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({request: prompt})
      });

      if (!r.ok) {
        out.innerHTML = '<p>Request failed.</p>';
        return;
      }

      const data = await r.json();
      const ex = data.execution || {};
      out.innerHTML = `
        <h3>Result</h3>
        <p><b>Address:</b> ${ex.address || 'n/a'}</p>
        <p><b>NDVI:</b> ${ex.mean_ndvi ?? 'n/a'}</p>
        <p><b>Fuel Class:</b> ${ex.fuel_class || 'n/a'}</p>
        <p><b>Recommendation:</b> ${data.final_response}</p>
        <details>
          <summary>Structured JSON</summary>
          <pre>${JSON.stringify(data, null, 2)}</pre>
        </details>
      `;
    };
  </script>
</body>
</html>
"""


@app.get("/")
def home():
    html = render_template_string(INDEX_HTML)
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
