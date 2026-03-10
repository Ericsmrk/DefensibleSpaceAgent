# Defensible Space Agent — Project State & Flow

**Last updated:** March 7, 2025  
**Purpose:** Accurate snapshot of the project for handoff (e.g., GPT) and understanding how everything works.

---

## 1. What the project is

- **Name:** Defensible Space Agent (ClearSafe)
- **Domain:** Wildfire defensible-space assessment (California-focused).
- **Stack:** Python 3, Flask, OpenAI API (GPT), optional Google Maps/Geocoding.
- **Entry points:** Run from project root (folder containing `web_app.py` and `.env`).
  - **Web:** `python web_app.py` → `http://localhost:8000`
  - **CLI:** `python demo.py` (runs `run_agent()` on example requests)
- **Setup:** Create venv, activate, `pip install -r requirements.txt`. Copy `.env.example` to `.env`, set `OPENAI_API_KEY` and `GOOGLE_MAPS_KEY` (no quotes). For NDVI: run `earthengine authenticate` (or `.\.venv\Scripts\earthengine.exe authenticate` on Windows), then set `EARTHENGINE_PROJECT=your-gcp-project-id` in `.env` (Google Cloud project with Earth Engine API enabled).

---

## 2. Repository layout

```
DefensibleSpaceAgent/
├── web_app.py              # Flask app: UI + API routes
├── demo.py                 # CLI: runs run_agent() on example strings
├── requirements.txt        # flask, python-dotenv, pytest, earthengine-api
├── .env.example            # OPENAI_API_KEY, GOOGLE_MAPS_KEY, optional EARTHENGINE_PROJECT (copy to .env)
├── src/
│   ├── __init__.py
│   ├── agent.py            # Main pipeline: run_agent(), run_planner_only()
│   ├── llm_client.py       # OpenAI API client (chat_json, chat_text)
│   ├── prompts.py         # PLANNER_SYSTEM, GENERATOR_SYSTEM, VALIDATOR_SYSTEM, REPORTER_SYSTEM
│   ├── tools.py           # geocode_google, compute_mean_ndvi, classify_fuel
│   ├── validators.py      # validate_plan, validate_tool_args, validate_coordinates
│   └── schemas.py         # Dataclasses (Plan, ToolArgs, ExecutionResult, etc.) — not used in runtime flow
├── tests/
│   ├── test_agent.py
│   ├── test_web_app.py
│   └── test_validators.py
└── docs/
    ├── architecture.md
    ├── llm_tool_sequence.md
    ├── validation_checks.md
    ├── prompt_templates.md
    └── deploy_clearsafe_org.md
```

---

## 3. High-level flow

There are **two main user-facing flows**:

### Flow A: “Run planner” (address-only baseline)

- **Trigger:** User clicks “Run planner” in the UI (or could call `POST /api/plan`).
- **Input:** Single address string (from Places autocomplete or typed).
- **Path:** `web_app.py` → `POST /api/plan` → `LLMClient.chat_text(PLANNER_SYSTEM, PLANNER_PROMPT.format(address=...))`.
- **No** `run_agent()`, no tools, no geocode/NDVI. Just one OpenAI call with a California wildfire baseline prompt.
- **Output:** Short “Baseline Fire Danger Overview” text shown in the UI (and in `plan.response` in JSON).

### Flow B: “Analyze Fire Risk” / “Run Assessment” (full pipeline)

- **Trigger:** “Analyze Fire Risk” or “Run Assessment (manual)” in the UI → `POST /api/assess`.
- **Input:** JSON body with `request` (and optionally `address`, `lat`, `lng`). The backend currently derives address from `request` inside the agent; explicit `address`/`lat`/`lng` from the payload are **not yet** passed into the tools (see `web_app.py` comment in `assess()`).
- **Path:** `web_app.py` → `POST /api/assess` → `run_agent(user_request)` in `src/agent.py`.
- **Output:** JSON with `plan`, `tool_args`, `validation`, `execution`, `final_response`.

---

## 4. Detailed flow of `run_agent(user_request)` (Flow B)

This is the core pipeline in `src/agent.py`:

1. **Planner (LLM)**  
   - `LLMClient.chat_json(PLANNER_SYSTEM, planner_user, fallback=_fallback_plan(user_request))`  
   - Produces a **plan** JSON: `domain`, `user_goal`, `steps` (each step: `step_id`, `objective`, `tool`, `constraints`).  
   - Allowed tools: `geocode_google`, `compute_mean_ndvi`, `classify_fuel`, or `None`.

2. **Plan validation (rule-based)**  
   - `validate_plan(plan)` in `src/validators.py`: checks required keys and that every step’s `tool` is in `ALLOWED_TOOLS`.

3. **Generator (LLM)**  
   - `LLMClient.chat_json(GENERATOR_SYSTEM, "Given plan: ... Generate tool args for request: ...", fallback=_fallback_tool_args(user_request))`  
   - Produces **tool_args** JSON: `address`, `buffer_m`, `start`, `end`, `cloud_pct`.

4. **Tool-args validation (rule-based)**  
   - `validate_tool_args(tool_args)`: required keys, `buffer_m` in 1..500, `cloud_pct` in 0..100, non-empty `address`.

5. **Validator (LLM)**  
   - `LLMClient.chat_json(VALIDATOR_SYSTEM, ...)`  
   - Produces `passed` (bool) and `reasons` (list).  
   - If **any** of plan, tool_args, or validator checks fail → return early with `validation.passed: False` and no tool execution.

6. **Geocode**  
   - `geocode_google(tool_args["address"])` in `src/tools.py`.  
   - If `GOOGLE_MAPS_KEY` is set: real Google Geocoding API.  
   - Else: mock (known addresses or hash-based lat/lon).  
   - `validate_coordinates(lat, lon)`; on failure, return with error, no NDVI.

7. **NDVI**  
   - `compute_mean_ndvi(lat, lon, buffer_m=..., start=..., end=..., cloud_pct=...)`.  
   - **Current implementation:** deterministic mock (hash-based), no real satellite API.

8. **Fuel class**  
   - `classify_fuel(ndvi)` (rule-based thresholds from NDVI → string).

9. **Reporter (LLM)**  
   - `LLMClient.chat_text(REPORTER_SYSTEM, "Use this result JSON and produce concise actions: ...", fallback=...)`  
   - Produces the **final_response** text for the user.

10. **Return**  
    - `{ plan, tool_args, validation, execution, final_response }`.  
    - `execution` contains: `address`, `latitude`, `longitude`, `mean_ndvi`, `fuel_class`, `confidence`, `evidence`.

---

## 5. Web app API endpoints

| Method + Path         | Purpose |
|-----------------------|--------|
| `GET /`               | Serves the single-page HTML (ClearSafe UI with map, address search, buttons). |
| `POST /api/geocode`   | Body: `{ "address" }`. Returns `{ lat, lon, source }` via `geocode_google()`. Not used by the current UI (UI uses Google Places + hidden lat/lng). |
| `POST /api/plan`      | Body: `{ "address" }`. Runs the **planner-only** flow (Flow A); returns `{ plan: { response } }`. |
| `POST /api/assess`    | Body: `{ "request" }` (optional: `address`, `lat`, `lng`). Runs **full pipeline** (Flow B) via `run_agent(payload["request"])`. |
| `POST /api/joke`      | Body: `{ "word" }`. Demo endpoint: OpenAI one-off joke. |
| `GET /healthz`        | `{ "ok": true }`. |
| `GET /version`        | `{ "version": "with-geocode", "has_geocode_ui": true }`. |

---

## 6. Configuration and secrets

- **`.env`** (from `.env.example`): `OPENAI_API_KEY`, `GOOGLE_MAPS_KEY`. Not committed.
- **OpenAI:** All LLM steps (planner, generator, validator, reporter) and the `/api/plan` and `/api/joke` endpoints need `OPENAI_API_KEY`. If missing, the client uses fallbacks (e.g. hardcoded plan/args and fallback text).
- **Google:** Used for geocoding in `tools.geocode_google` and for the Maps/Places script in the HTML. If `GOOGLE_MAPS_KEY` is missing, geocoding uses mock data; the map may still load if the key is set in the template (e.g. from env) or show a placeholder.

---

## 7. UI behavior (relevant to flow)

- **Address:** User types in the address field; Google Places Autocomplete (US only) sets a selected place. Hidden fields `selected_address`, `selected_lat`, `selected_lng` are updated; “Analyze Fire Risk” is enabled only when a valid place is selected.
- **Run planner:** Uses `hidden_address` or the visible address input; sends only `address` to `/api/plan`. No lat/lng required.
- **Analyze Fire Risk / Run Assessment:** Send `request` (and optional address/lat/lng) to `/api/assess`. The backend currently uses `run_agent(request)` and derives address from the request text; the payload’s `address`/`lat`/`lng` are **not** yet forwarded to the agent/tools (documented in `web_app.py`).

---

## 8. Current limitations / gaps

- **Payload address/lat/lng:** `/api/assess` does not pass through `address`, `lat`, `lng` from the request body into `run_agent` or into the tools; the agent infers address from the free-text `request`.
- **NDVI:** Implemented as a deterministic mock (no real satellite or NDVI API).
- **Schemas:** `src/schemas.py` defines dataclasses (e.g. `Plan`, `ToolArgs`) but the live code uses plain dicts; schemas are not part of the runtime flow.
- **Two planner prompts:** The **full pipeline** in `agent.py` uses `prompts.PLANNER_SYSTEM` (short, JSON plan). The **Run planner** button in the UI uses a different, long-form California baseline prompt defined in `web_app.py` (`PLANNER_SYSTEM` + `PLANNER_PROMPT`); that prompt is not used in `run_agent()`.

---

## 9. Testing

- **tests/test_agent.py:** Agent pipeline behavior.
- **tests/test_web_app.py:** Flask routes (e.g. `/api/plan`, `/api/assess`, `/api/joke`).
- **tests/test_validators.py:** `validate_plan`, `validate_tool_args`, `validate_coordinates`.

Run: `pytest` (from repo root, with venv activated).

---

## 10. One-sentence summary

**Defensible Space Agent** is a Flask app that (1) exposes a “Run planner” endpoint that returns a California wildfire baseline from an address using one OpenAI call, and (2) exposes an “Assess” endpoint that runs a multi-step pipeline (plan → tool-args → validations → geocode → mock NDVI → fuel class → reporter) via `run_agent()`, with all LLM steps using the OpenAI API and geocoding using Google or a mock.

You can share this file with GPT or others to get an accurate state and flow of the project.
