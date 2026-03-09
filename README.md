# Defensible Space Agent

Structured multi-LLM + tools prototype for wildfire defensible-space assessment.

## Domain
**Other Instructor-Approved Domain**: Wildfire Defensible-Space Assessment Agent.

## What it demonstrates
- **Tiered assessment workflow**: baseline (address-level) vs full (property-focused) California wildfire assessments.
- **Multi-LLM pipeline**: planning LLM → validator LLM → reporter LLM (with deterministic rule-based fallbacks when LLMs are unavailable).
- **Tools layer**: geocoding, NDVI stub (no third‑party satellite provider wired), and fuel‑class classification from NDVI.
- **Strong validation layer**: explicit rules for plan shape, tool arguments, coordinate sanity, and California‑only scope.
- **Structured intermediates**: the planner produces an execution spec that downstream validators/executor use to drive the pipeline.

## Architecture overview

- **Frontend**: a single‑page UI (served by `web_app.py`) that:
  - Lets the user search/select a US address using Google Places.
  - Lets the user choose **Full assessment** vs **Baseline**.
  - Calls `/api/plan` to preview the internal execution plan.
  - Calls `/api/assess` to run the full agent pipeline and render results (tier label, NDVI, fuel class, context bullets, and narrative recommendations).
- **Backend (Flask)**: `web_app.py` exposes:
  - `GET /` – serves the ClearSafe UI.
  - `POST /api/plan` – runs the **planner only** and returns the structured plan plus a human‑readable planner summary.
  - `POST /api/assess` – runs the **full agent pipeline** (planner → validators → executor → reporter).
  - `POST /api/geocode` – direct Google geocoding helper (used by potential clients; planner/executor geocode via tools).
  - `POST /api/joke` – small demo endpoint using the same `LLMClient`.
  - `GET /healthz` – health probe.
  - `GET /version` – lightweight version marker for deployments.
- **Core agent orchestration**: `src/agent.py`:
  - Builds planner context from the user request, address, coordinates, tier preference, and optional photo metadata.
  - Runs the planner LLM (or a deterministic fallback) to produce an **execution spec**.
  - Normalizes and validates the plan against a strict schema and California‑only rules.
  - Derives tool arguments from the plan constraints and context.
  - Validates tool arguments and coordinates.
  - Executes the steps in the plan using internal tools in `src/tools.py` and built‑in placeholders for context steps.
  - Calls the reporter LLM to turn structured evidence into the final human‑readable assessment.

### Agent pipeline (backend)

At a high level, `/api/assess` runs:

1. **Planner**
   - Input: JSON context describing the user request, address, coordinates (if any), and assessment preference.
   - LLM prompt: `PLANNER_SYSTEM` + `PLANNER_PROMPT` in `src/prompts.py`.
   - Output: a structured **execution spec** with:
     - `request_type`: `"baseline_free_tier"`, `"full_paid_tier"`, `"incomplete"`, or `"unsupported"`.
     - `assessment_mode`: `"address_level_baseline"`, `"property_level_environmental_assessment"`, etc.
     - `location_strategy`: whether to use provided coordinates or run geocoding.
     - `analysis_modules`: conceptual stages (hazard, terrain, vegetation, etc.).
     - `steps`: ordered internal tools like `"resolve_location"`, `"compute_property_ndvi"`, `"classify_property_fuel"`, `"generate_full_report"`, etc.
     - `constraints`: e.g. `buffer_m`, `cloud_pct`, optional `photo_count` and `date_window`.
     - `recommended_next_action` and `planner_summary` for UI display.
   - If the LLM is unavailable or returns invalid JSON, `_fallback_execution_spec` in `src/agent.py` generates a deterministic plan with the same schema, using:
     - California‑only heuristics.
     - Simple intent classification (baseline vs full vs incomplete vs unsupported).

2. **Plan normalization and validation**
   - `src.validators.normalize_plan` coerces legacy/partial planner outputs into the canonical schema and normalizes tool and tier names.
   - `src.validators.validate_plan` enforces:
     - Only allowed tools and analysis modules.
     - Step ordering, contiguity, and dependency rules.
     - Consistency between `request_type`, `assessment_mode`, `execution_ready`, `location_strategy`, and `steps`.
     - Tier‑specific constraints (e.g., baseline plans must not include property‑level tools; full plans must end with `generate_full_report`).

3. **Tool‑argument derivation and validation**
   - `_tool_args_from_plan` in `src/agent.py` builds tool arguments (address, NDVI window, buffer, cloud cover) from `plan.constraints` and context.
   - If the plan still requires address‑level geocoding and no address is present, `_fallback_tool_args` attempts to heuristically extract an address string from the user request.
   - `src.validators.validate_tool_args` checks:
     - Address presence when `resolve_location` is required.
     - NDVI date window when `compute_property_ndvi` is present.
     - `buffer_m` and `cloud_pct` are within allowed ranges.

4. **Validator LLM**
   - `VALIDATOR_SYSTEM` in `src/prompts.py` drives a small JSON‑only LLM that receives a summary of plan/tool‑arg validity and returns:
     - `{"passed": bool, "reasons": [...]}`.
   - If the LLM is unavailable, `_fallback_validation` returns a conservative allow decision.
   - If any of the three validators (plan, tool args, validator LLM) fail, the pipeline stops and returns a blocked result to the client.

5. **Executor (tools + context synthesis)**
   - For each step in `plan.steps`, the executor in `src/agent.py`:
     - Handles `"resolve_location"` by calling `geocode_google` in `src/tools.py`.
     - Gathers coarse hazard/terrain/regional vegetation summaries as structured text for the reporter.
     - Calls `compute_mean_ndvi` and `classify_fuel` for property‑centered vegetation/fuel interpretation (full tier only).
     - Sets placeholders for property‑slope, vegetation‑proximity, and photo‑analysis steps (these are currently non‑wired stubs).
     - Assembles a `report` object describing whether this is a baseline or full report and what evidence was used.
   - The executor maintains an `execution` dict with keys like `tier`, `address`, `latitude`, `longitude`, `mean_ndvi`, `fuel_class`, `hazard_context`, etc., which is returned in API responses.

6. **Reporter LLM**
   - `REPORTER_SYSTEM` in `src/prompts.py` instructs the LLM to:
     - Turn the structured `plan` and `execution` evidence into concise, prioritized homeowner actions and interpretation.
   - If the LLM is unavailable, a short deterministic baseline/full summary is returned instead.

### Assessment tiers and behavior

- **Baseline (free) tier (`baseline_free_tier`)**
  - Address‑level California wildfire overview.
  - Uses location resolution (when needed) plus:
    - Hazard context.
    - Terrain context (regional).
    - Regional vegetation / land‑cover context.
  - Does **not**:
    - Compute parcel‑centered NDVI.
    - Classify property fuel load.
    - Analyze vegetation proximity rings.
    - Analyze photos.
  - Produces a lightweight baseline report and narrative recommendations that emphasize limitations.

- **Full (paid) tier (`full_paid_tier`)**
  - Property‑focused California wildfire/defensible‑space assessment.
  - Includes baseline context plus:
    - Property‑centered NDVI (when a satellite provider is configured).
    - Fuel classification from NDVI.
    - Property‑slope and vegetation‑proximity placeholders (currently stubbed in this build).
    - Optional structure‑photo analysis when photos are present (currently stubbed; no image API calls wired).
  - Produces CAL FIRE‑aligned recommendations and a full report object.

### Behavior without external keys

- **Without `OPENAI_API_KEY`**
  - All LLM calls (`LLMClient`) fall back to deterministic, rule‑based behavior:
    - Planner: `_fallback_execution_spec` generates a safe, California‑only plan.
    - Validator: `_fallback_validation` marks validation as passed.
    - Reporter: returns a short canned baseline/full summary.
  - This allows the pipeline and tests to run deterministically for grading or offline demos.

- **Without `GOOGLE_MAPS_KEY`**
  - `geocode_google` returns `None` and a structured error instead of fabricating coordinates.
  - Any pipeline path that requires geocoding will fail validation and return an error like “Could not obtain valid coordinates.”
  - The **UI still loads** (using a placeholder API key), but address‑based geocoding and map selection will not function fully until a real key is configured.

## Quickstart (CLI)
```bash
python demo.py
```

## Quickstart (Web UI)
```bash
pip install -r requirements.txt
python web_app.py
```
Open: `http://localhost:8000`

## Optional environment variables for live APIs
- `OPENAI_API_KEY` for ChatGPT calls.
- `GOOGLE_MAPS_KEY` for Google geocoding.

Without keys, the project runs in deterministic mock mode for instructor reproducibility.


## GitHub Pages (temporary frontend)
You can publish `index.html` as a temporary public frontend right now.

1. Push this repo to GitHub (branch `work` or `main`).
2. In GitHub: **Settings -> Pages**
3. Under **Build and deployment**, choose:
   - Source: **Deploy from a branch**
   - Branch: `work` (or `main`)
   - Folder: `/ (root)`
4. Save and wait for the Pages URL to appear.

Notes:
- On GitHub Pages, the app runs in **frontend-only mock mode** unless you provide an API Base URL in the page UI.
- If you have the Flask backend deployed (Render/Railway/etc.), paste that URL into the API Base field to run live assessments.


## Keys and secrets (required for live online mode)
Do **not** hardcode or commit keys into this repository.

- Local development: copy `.env.example` to `.env` and set values there.
- Hosted backend (Render/Railway/Fly): set `OPENAI_API_KEY` and `GOOGLE_MAPS_KEY` in the provider dashboard environment variables.
- GitHub Pages is static-only: never put API keys in `index.html`/JavaScript because they become public. Use Pages as frontend and call your hosted backend API instead.

## Deploy to your domain (e.g., clearsafe.org)
1. Push this repo to GitHub.
2. Create a web service on Render (or Railway/Fly) using:
   - build command: `pip install -r requirements.txt && pip install gunicorn`
   - start command: `gunicorn web_app:app --bind 0.0.0.0:$PORT`
3. Set environment variables in host dashboard (`OPENAI_API_KEY`, `GOOGLE_MAPS_KEY`).
4. In your DNS provider, add:
   - `A`/`ALIAS` record for `@` pointing to host target
   - `CNAME` for `www` pointing to your host URL
5. Attach custom domain in hosting dashboard and enable TLS.

See `docs/deploy_clearsafe_org.md` for step-by-step details.

## Project structure
- `src/agent.py` – planner/validator/executor/reporter orchestration pipeline.
- `src/llm_client.py` – thin HTTP client around OpenAI Chat Completions (JSON/text helpers, fallbacks when key is missing).
- `src/tools.py` – geocoding + NDVI stub + fuel‑classification tools used by the executor.
- `src/validators.py` – normalization and strict validation for planner outputs, tool args, and coordinates.
- `src/prompts.py` – prompt templates for planner, validator, and reporter LLMs.
- `src/schemas.py` – dataclasses for the internal execution spec and agent outputs.
- `web_app.py` – Flask app serving the ClearSafe UI and JSON API endpoints.
- `tests/` – validator and orchestration checks.

## Security
- Do not commit API keys.
- Use environment variables only.
