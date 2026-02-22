from __future__ import annotations

from flask import Flask, jsonify, render_template_string, request

from src.agent import run_agent

app = Flask(__name__)

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
    .muted { color: #666; }
    pre { background: #f6f6f6; padding: .8rem; overflow-x: auto; }
  </style>
</head>
<body>
  <h1>ClearSafe</h1>
  <p class="sub">Wildfire defensible-space assistant</p>

  <label for="prompt">What should we assess?</label>
  <textarea id="prompt" placeholder="Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca"></textarea>
  <br />
  <button id="run">Run Assessment</button>

  <div id="out" class="card" style="display:none;"></div>

  <script>
    const out = document.getElementById('out');
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
    return render_template_string(INDEX_HTML)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
