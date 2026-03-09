from __future__ import annotations

import json
import logging
import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, render_template_string, request, Response

logger = logging.getLogger(__name__)

from src.agent import run_agent, run_planner_only, normalize_plan_for_provided_coordinates
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
    .planner-response .planner-next-steps-header { color: var(--accent); font-weight: 600; }
    .planner-response .planner-next-steps-choice { color: #ffffff; }
    .intro-text { line-height: 1.65; margin: 0.5rem 0 1rem 0; color: var(--text-muted); font-size: 0.95rem; }
    .intro-steps { margin: 1rem 0; padding-left: 1.25rem; }
    .intro-steps li { margin: 0.4rem 0; color: var(--text); }
    .assessment-choice { margin: 1rem 0 1.25rem 0; }
    .assessment-choice label { display: flex; align-items: flex-start; gap: 0.6rem; margin: 0.5rem 0; cursor: pointer; }
    .assessment-choice input[type="radio"] { margin-top: 0.2rem; accent-color: var(--accent); }
    .assessment-choice .choice-desc { font-size: 0.875rem; color: var(--text-muted); margin-top: 0.15rem; }
    .recommend { font-size: 0.85rem; color: var(--accent); margin-top: 0.5rem; }
    .result-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .result-title { margin: 0 0 0.35rem 0; font-size: 1.1rem; font-weight: 600; }
    .result-address { margin: 0; font-size: 0.9rem; color: var(--text-muted); }
    .pill {
      display: inline-flex;
      align-items: center;
      padding: 0.18rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .pill-tier {
      background: rgba(249, 115, 22, 0.12);
      color: var(--accent);
      border: 1px solid rgba(249, 115, 22, 0.4);
    }
    .pill-status-ok {
      background: rgba(34, 197, 94, 0.12);
      color: var(--success);
      border: 1px solid rgba(34, 197, 94, 0.45);
    }
    .pill-status-blocked {
      background: rgba(220, 38, 38, 0.12);
      color: var(--danger);
      border: 1px solid rgba(220, 38, 38, 0.45);
    }
    .result-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 0.9rem;
      margin: 0.25rem 0 0.75rem 0;
    }
    .metric-card {
      background: var(--bg);
      border-radius: 10px;
      border: 1px solid var(--border);
      padding: 0.75rem 0.9rem;
    }
    .metric-label {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-muted);
      margin-bottom: 0.2rem;
    }
    .metric-value {
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 0.15rem;
    }
    .metric-caption {
      font-size: 0.8rem;
      color: var(--text-muted);
    }
    .result-section {
      margin-top: 0.6rem;
    }
    .result-section-title {
      font-size: 0.9rem;
      font-weight: 600;
      margin: 0 0 0.25rem 0;
    }
    .result-text {
      font-size: 0.9rem;
      line-height: 1.6;
      color: var(--text);
      margin: 0;
    }
    .result-subtext {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 0.35rem;
    }
    .result-details {
      margin-top: 0.9rem;
    }
    .result-details summary {
      cursor: pointer;
      font-size: 0.85rem;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <h1>ClearSafe</h1>
  <p class="sub">Fire clearance & defensible-space assessment</p>

  <section class="card" aria-label="Introduction">
    <h2 class="card-title">Welcome to ClearSafe</h2>
    <p class="intro-text">
      This app helps you assess wildfire defensible-space and fire clearance for a property in the US.
      You enter an address, choose the type of assessment, then run the planning step. After reviewing the plan, you can run the full analysis to get data (when available), fuel class, and recommendations. NDVI and some environmental metrics depend on external data sources and may be unavailable in some deployments.
    </p>
    <p class="intro-text" style="margin-bottom: 0;"><strong>How to use:</strong></p>
    <ol class="intro-steps">
      <li>Enter a US address below and select a result from the list.</li>
      <li>Choose <strong>Full assessment</strong> (vegetation, fuel, recommendations) or <strong>Baseline</strong> (address-level overview only).</li>
      <li>Click <strong>Run planner</strong> to generate the assessment plan.</li>
      <li>After reviewing the plan, click <strong>Analyze Fire Risk</strong> to run the agent and get your results.</li>
    </ol>
  </section>

  <section class="card" aria-label="Property search">
    <h2 class="card-title">Find your property</h2>
    <p class="muted" style="margin: 0 0 0.75rem 0;">Start typing a US address to search. Select a result, then choose Full or Baseline assessment and run the planner.</p>
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

      <div class="assessment-choice">
        <p class="card-title" style="margin-bottom: 0.25rem;">Assessment type</p>
        <label>
          <input type="radio" name="assessment_type" value="full" id="assessment-full" checked />
          <span>
            <strong>Full assessment</strong>
            <span class="choice-desc">Vegetation (NDVI), fuel classification, and defensible-space recommendations.</span>
          </span>
        </label>
        <label>
          <input type="radio" name="assessment_type" value="baseline" id="assessment-baseline" />
          <span>
            <strong>Baseline</strong>
            <span class="choice-desc">Address-level overview only; no full environmental pipeline.</span>
          </span>
        </label>
        <p class="recommend">We recommend Full assessment for actionable defensible-space advice.</p>
      </div>

      <p class="muted" style="margin: 1rem 0 .5rem 0;">Run the planner to build the assessment plan for your address and chosen type.</p>
      <button type="button" id="run-plan" class="btn btn-primary">Run planner</button>
      <div id="plan-out" class="card" style="display:none; margin-top: 1rem;"></div>
      <p class="muted" style="margin: 1rem 0 .5rem 0;">After reviewing the plan above, run the full pipeline to get results.</p>
      <button type="button" id="analyze-btn" class="btn btn-primary" disabled>Analyze Fire Risk</button>
    </form>
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
          var isNextStepsHeader = t.indexOf('Possible Next Steps') >= 0 && t.endsWith(':');
          var numMatch = t.match(/^(\\d+)\\./);
          var isChoice = numMatch && (numMatch[1] >= 1 && numMatch[1] <= 12);
          if (isNextStepsHeader) return '<span class="planner-next-steps-header">' + escaped + '</span>';
          if (isChoice) return '<span class="planner-next-steps-choice">' + escaped + '</span>';
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

    function getAssessmentType() {
      var full = document.getElementById('assessment-full');
      return (full && full.checked) ? 'full' : 'baseline';
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
        lng: lng,
        assessment_type: getAssessmentType()
      };

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

      var tierRaw = ex.tier || (data.plan && data.plan.request_type) || '';
      var tierLabel = 'Assessment';
      if (tierRaw === 'full_paid_tier') tierLabel = 'Full assessment';
      else if (tierRaw === 'baseline_free_tier') tierLabel = 'Baseline overview';

      var validation = data.validation || {};
      var passed = validation.passed !== false;
      var statusLabel = passed ? 'Completed' : 'Blocked';
      var statusClass = passed ? 'pill-status-ok' : 'pill-status-blocked';

      var ndviVal = ex.mean_ndvi != null ? ex.mean_ndvi : null;
      var ndviDisplay = ndviVal != null ? ndviVal : 'Not available';
      var ndviCaption = ndviVal != null
        ? 'Higher values usually mean denser, greener vegetation.'
        : 'NDVI is not available in this deployment or for this location.';

      var fuel = ex.fuel_class || 'No Data';
      var fuelCaption = fuel === 'No Data'
        ? 'Fuel classification is unavailable when NDVI is missing.'
        : 'Interpretation based on available vegetation signal.';

      var addressDisplay = escapeHtml(ex.address || addr || 'n/a');
      var mainText = escapeHtml(data.final_response || '');

      var hazardSummary = (ex.hazard_context && ex.hazard_context.summary) || '';
      var terrainSummary = (ex.terrain_context && ex.terrain_context.summary) || '';
      var vegSummary = (ex.regional_vegetation_context && ex.regional_vegetation_context.summary) || '';

      var contextBits = [];
      if (hazardSummary) contextBits.push('• ' + escapeHtml(hazardSummary));
      if (terrainSummary) contextBits.push('• ' + escapeHtml(terrainSummary));
      if (vegSummary) contextBits.push('• ' + escapeHtml(vegSummary));
      var contextHtml = contextBits.length
        ? '<div class="result-section"><h4 class="result-section-title">What this is based on</h4><p class="result-text">' + contextBits.join('<br>') + '</p></div>'
        : '';

      var baselineWorkflow = data.baseline_workflow || null;
      var baselineReport = baselineWorkflow && baselineWorkflow.final_report ? baselineWorkflow.final_report : null;
      var isBaselineTier = tierRaw === 'baseline_free_tier';

      var resultTitle = 'Assessment result';
      if (isBaselineTier && baselineReport && baselineReport.report_title) {
        resultTitle = baselineReport.report_title;
      }

      var headerHtml =
        '<div class="result-header">' +
          '<div>' +
            '<div class="pill pill-tier">' + escapeHtml(tierLabel) + '</div>' +
            '<h3 class="result-title">' + escapeHtml(resultTitle) + '</h3>' +
            '<p class="result-address">' + addressDisplay + '</p>' +
          '</div>' +
          '<div>' +
            '<div class="pill ' + statusClass + '">' + escapeHtml(statusLabel) + '</div>' +
          '</div>' +
        '</div>';

      var bodyHtml = '';

      if (isBaselineTier && baselineReport) {
        var sections = baselineReport.sections || {};

        function sectionBlock(label, key) {
          var text = sections[key] || '';
          if (!text || !String(text).trim()) return '';
          return (
            '<div class="result-section">' +
              '<h4 class="result-section-title">' + escapeHtml(label) + '</h4>' +
              '<p class="result-text">' + escapeHtml(String(text)) + '</p>' +
            '</div>'
          );
        }

        var summaryText = baselineReport.summary || '';
        if (summaryText && String(summaryText).trim()) {
          bodyHtml +=
            '<div class="result-section">' +
              '<h4 class="result-section-title">Summary</h4>' +
              '<p class="result-text">' + escapeHtml(String(summaryText)) + '</p>' +
            '</div>';
        }

        bodyHtml += sectionBlock('California scope validation', 'california_scope_validation');
        bodyHtml += sectionBlock('Fire hazard context', 'fire_hazard_context');
        bodyHtml += sectionBlock('Terrain context', 'terrain_context');
        bodyHtml += sectionBlock('Regional vegetation context', 'regional_vegetation_context');
        bodyHtml += sectionBlock('Limitations', 'limitations');
      } else {
        var metricsHtml =
          '<div class="result-grid">' +
            '<div class="metric-card">' +
              '<div class="metric-label">NDVI (vegetation index)</div>' +
              '<div class="metric-value">' + ndviDisplay + '</div>' +
              '<div class="metric-caption">' + ndviCaption + '</div>' +
            '</div>' +
            '<div class="metric-card">' +
              '<div class="metric-label">Fuel class</div>' +
              '<div class="metric-value">' + escapeHtml(fuel) + '</div>' +
              '<div class="metric-caption">' + fuelCaption + '</div>' +
            '</div>' +
          '</div>';

        var ndviMeta = (ex.evidence && ex.evidence.ndvi) || {};
        var ndviThumbUrl = ndviMeta.thumb_url || null;
        var ndviMapHtml = '';
        if (ndviThumbUrl) {
          ndviMapHtml =
            '<div class="result-section">' +
              '<h4 class="result-section-title">NDVI ring map</h4>' +
              '<p class="result-text">Satellite-derived vegetation index (NDVI) around the address within the analysis buffer. Brighter colors usually indicate denser, greener vegetation that can act as wildfire fuel.</p>' +
              '<img src="' + escapeHtml(String(ndviThumbUrl)) + '" alt="NDVI map" style="max-width:100%; border-radius:8px; border:1px solid var(--border); margin-top:0.5rem;" />' +
            '</div>';
        }

        var actionsHtml =
          '<div class="result-section">' +
            '<h4 class="result-section-title">Top actions and interpretation</h4>' +
            '<p class="result-text">' + mainText + '</p>' +
            '<p class="result-subtext">These recommendations are based on California-focused wildfire defensible-space guidance and the evidence listed below.</p>' +
          '</div>';

        bodyHtml = metricsHtml + ndviMapHtml + actionsHtml + contextHtml;
      }

      var debugHtml =
        '<details class="result-details"><summary>View full structured output</summary><pre>' +
          escapeHtml(JSON.stringify(data, null, 2)) +
        '</pre></details>';

      out.innerHTML = headerHtml + bodyHtml + debugHtml;
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
      var payload = { address: address, assessment_type: getAssessmentType() };
      if (hiddenLat.value && hiddenLng.value) {
        payload.lat = hiddenLat.value.trim();
        payload.lng = hiddenLng.value.trim();
      }
      var r = await fetch('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
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


def _assessment_preference_from_payload(payload):
    """Map UI assessment_type ('full'|'baseline') to planner request_type."""
    at = (payload.get("assessment_type") or payload.get("assessment_preference") or "").strip().lower()
    # Canonical tier names
    if at in ("baseline", "baseline_free_tier"):
        return "baseline_free_tier"
    if at in ("full", "full_paid_tier"):
        return "full_paid_tier"
    # Legacy values (compat)
    if at == "address_baseline":
        return "baseline_free_tier"
    if at == "full_property_assessment":
        return "full_paid_tier"
    return None


@app.post("/api/plan")
def plan():
    """Run the internal planner (structured execution spec). Returns plan JSON and user-facing planner_summary."""
    payload = request.get_json(silent=True) or {}
    address = (payload.get("address") or "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400
    lat = _parse_float(payload.get("lat"))
    lng = _parse_float(payload.get("lng"))
    has_coords = lat is not None and lng is not None
    pref = _assessment_preference_from_payload(payload)
    planner_context = {
        "user_request": f"Assess wildfire risk for {address}",
        "provided_address": address,
        "provided_coordinates": {"lat": lat, "lng": lng} if has_coords else None,
        "source": "google_places_selection" if has_coords else "address_only",
    }
    if pref:
        planner_context["assessment_preference"] = pref
    try:
        plan_result = run_planner_only(json.dumps(planner_context))
        if has_coords:
            plan_result = normalize_plan_for_provided_coordinates(plan_result)
        response_text = plan_result.get("planner_summary") or (
            "Planner produced a structured plan. Run a full assessment to execute it."
        )
        return jsonify({"plan": plan_result, "response": response_text})
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


def _parse_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@app.post("/api/assess")
def assess():
    payload = request.get_json(silent=True) or {}
    user_request = (payload.get("request") or "").strip()
    if not user_request:
        return jsonify({"error": "request is required"}), 400
    address = (payload.get("address") or "").strip() or None
    lat = _parse_float(payload.get("lat"))
    lng = _parse_float(payload.get("lng"))
    uploaded_photos_present = payload.get("uploaded_photos_present")
    uploaded_photos_count = payload.get("uploaded_photos_count")
    # Debug: log incoming body so we can verify UI sends address/lat/lng when place is selected
    logger.info(
        "assess request: request=%r address=%r lat=%s lng=%s",
        user_request[:80] if user_request else None,
        address,
        lat if lat is not None else "None",
        lng if lng is not None else "None",
    )
    pref = _assessment_preference_from_payload(payload)
    result = run_agent(
        user_request,
        address=address,
        lat=lat,
        lng=lng,
        assessment_preference=pref,
        uploaded_photos_present=bool(uploaded_photos_present) if uploaded_photos_present is not None else None,
        uploaded_photos_count=int(uploaded_photos_count) if str(uploaded_photos_count or "").strip().isdigit() else None,
    )
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
