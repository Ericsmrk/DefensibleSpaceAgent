## ClearSafe California – Defensible Space Agent (Version One)

Structured, multi‑LLM + tools prototype for **California‑only wildfire defensible‑space and wildfire property assessment** with Baseline (free) and Full (paid) tiers.

### 1. Project overview

- **Project name**: ClearSafe California – Defensible Space Agent  
- **Version**: **Version One (v1)** – current implementation baseline  
- **Domain**: California wildfire defensible‑space / wildfire property assessment  
- **Primary audience**:
  - Homeowners and residents seeking clearer wildfire/defensible‑space guidance in California
  - Sierra Land Management (SLM) and ClearSafe California stakeholders
  - Graduate‑level software engineering / agentic AI reviewers

**Elevator pitch**  
ClearSafe California is a prototype wildfire defensible‑space assessment system that combines a tiered assessment workflow (Baseline vs Full), a structured agent pipeline (planner → validators → executor → reporter), and tool integrations (geocoding, optional NDVI and fuel classification) to produce **California‑focused, CAL FIRE–aligned homeowner guidance** while explicitly modeling uncertainty and system limits.

This repository is the **authoritative source** for **Version One** of the implementation and documentation.

### 2. Assessment tiers in Version One

The system exposes two conceptual tiers. Only California locations are considered in‑scope.

#### 2.1 Baseline (Free Tier) – Address‑level overview

- **Goal**: Provide a **California address‑level wildfire baseline** using coarse regional context.  
- **Key behaviors (implemented in v1)**:
  - Accepts a California address and (optionally) coordinates.
  - Resolves location via Google Geocoding (when configured) or uses caller‑provided coordinates.
  - Validates that the location appears to be in California (coarse bounding‑box + geocode metadata).
  - Gathers **regional** context only:
    - wildfire hazard context (high‑level)
    - terrain context (qualitative, no DEM)
    - regional vegetation / land‑cover context (qualitative, no parcel fuel map)
  - Synthesizes a **structured Baseline report JSON** via a dedicated LLM prompt, then renders an address‑level homeowner narrative in the UI.

- **Deliberate omissions** (by design in v1):
  - **No parcel‑centered NDVI** computation in Baseline tier.
  - **No property‑level fuel classification**.
  - **No vegetation‑ring / proximity metrics**.
  - **No image / photo analysis**.
  - **No Fire Hazard Severity Zone labels or official ratings**.

#### 2.2 Full (Paid Tier) – Property‑focused assessment

- **Goal**: Provide a **property‑focused California wildfire / defensible‑space assessment** that builds on Baseline context and, when data are available, adds more detailed remote sensing signals.
- **Key behaviors (implemented in v1)**:
  - Includes all Baseline context (location resolution, hazard, terrain, regional vegetation).
  - When configured with **Google Earth Engine** (`earthengine-api` installed and authenticated):
    - Computes **property‑centered NDVI** around the address (Sentinel‑2, configurable date window and cloud threshold).
    - Derives coarse **fuel classification** from NDVI (e.g., “High Vegetation (High Fuel Load)”).
    - Optionally generates an NDVI visualization thumbnail used in the UI.
  - Uses an additional CAL FIRE–aligned LLM stage to synthesize:
    - prioritized homeowner action bands (Immediate / Near‑term / Seasonal/Ongoing)
    - zone‑based recommendations for Zone 0/1/2
    - structured follow‑up items and limitations
  - Returns a structured `execution` object and detailed recommendation JSON that the UI renders into a rich report.

- **Current placeholders / partial features in v1**:
  - **Property slope analysis**:
    - Implemented as a **placeholder**; no DEM or actual slope computation is connected.
    - The system records a “Not available in this build” summary.
  - **Vegetation proximity / rings**:
    - Implemented as a **placeholder**; no ring or distance‑band analysis is computed.
  - **Uploaded structure/property photo analysis**:
    - Recognized in the planner and execution spec and represented in the data model.
    - Execution step is a **placeholder only**; no image analysis API is wired.

### 3. High‑level architecture (Version One)

The architecture follows a **structured agent** pattern with an explicit separation between planning, validation, execution, and reporting.

- **Frontend (single‑page UI) – `web_app.py` / inline `INDEX_HTML`**
  - Google Maps + Places integration to select a US address (UI text mentions “US”, but the backend constrains the pipeline to California).
  - Radiobutton choice between **Baseline** and **Full** assessment.
  - Buttons:
    - **Run planner** (`POST /api/plan`)
    - **Analyze Fire Risk** (`POST /api/assess`)
  - Renders:
    - Planner summary response for `/api/plan`.
    - Structured Baseline and Full results (`execution`, Baseline report JSON, CAL FIRE–aligned plan) for `/api/assess`.

- **Backend (Flask) – `web_app.py`**
  - `GET /` – serves ClearSafe UI (single‑page HTML).
  - `POST /api/plan` – runs planner‑only path via `run_planner_only` and returns:
    - structured planner execution spec
    - human‑readable `planner_summary` text for the UI.
  - `POST /api/assess` – runs full agent pipeline via `run_agent` in `src/agent.py`.
  - `POST /api/geocode` – JSON wrapper around `geocode_google` (direct geocoding).
  - `POST /api/joke` – small demo endpoint using the same `LLMClient`.
  - `GET /healthz` – health probe.
  - `GET /version` – lightweight deployment marker used by hosting providers.

- **Structured agent core – `src/agent.py`**
  - Builds planner context from:
    - user request text
    - optional address and coordinates (from UI or API client)
    - assessment tier preference
    - optional photo metadata.
  - **Planner LLM** (`PLANNER_SYSTEM`/`PLANNER_PROMPT` in `src/prompts.py`):
    - Produces a strict **execution spec** JSON with:
      - `request_type` (`baseline_free_tier`, `full_paid_tier`, `incomplete`, `unsupported`)
      - `assessment_mode` (baseline vs property‑level, incomplete, unsupported)
      - `location_strategy` (use provided coordinates vs geocode)
      - `analysis_modules` (conceptual modules)
      - `steps` (ordered internal tools)
      - `constraints` (`buffer_m`, `cloud_pct`, optional `date_window`, `photo_count`)
      - `recommended_next_action` + `planner_summary`.
    - If the LLM is unavailable or invalid, a deterministic `_fallback_execution_spec` generates a safe California‑only plan.
  - **Plan normalization and validation** (`src.validators`):
    - Normalizes legacy planner shapes to canonical schema.
    - Enforces:
      - allowed tools and modules only
      - step ordering and dependency consistency
      - tier‑specific tool constraints (Baseline cannot use property‑level tools; Full must end in `generate_full_report`)
      - strict constraints on `buffer_m`, `cloud_pct`, and `photo_count`.
  - **Tool‑argument derivation and validation**:
    - Derives `tool_args` from `plan.constraints` + context.
    - Provides `_fallback_tool_args` that attempts to salvage an address from the free‑text request when needed.
    - Validates `tool_args` (address presence, NDVI date window, numeric ranges).
  - **Tier‑specific execution**:
    - **Baseline**:
      - Delegates to `execute_baseline_workflow` in `src/baseline_executor.py`.
      - Uses `BaselineToolContext` and a registry of Baseline tools in `src/baseline_tools.py`:
        - `resolve_location`
        - `validate_california_scope`
        - `gather_hazard_context`
        - `gather_terrain_context`
        - `gather_regional_vegetation_context`
        - `generate_baseline_report` (LLM synthesis + deterministic fallback).
      - Produces a structured `baseline_workflow` object and `final_report` JSON consumed by the UI.
    - **Full**:
      - Executes planner steps using internal tools in `src/tools.py`.
      - For CAL FIRE–aligned recommendations:
        - Uses `CALFIRE_RECOMMENDATION_SYSTEM` to produce a structured mitigation plan JSON, normalized via `_normalize_recommendation` with robust fallbacks.
      - Uses `GENERATOR_SYSTEM` to produce the final homeowner‑readable narrative when LLMs are available; otherwise falls back to deterministic text.

### 4. Data and control flow (request lifecycle)

At a high level, `/api/assess` (Full API) flows as:

1. **Planner**
   - Input: structured JSON context (user request, address, coordinates, preference, photo metadata).
   - Output: execution spec JSON (plan).
   - Fallback: deterministic execution spec with California‑only rules.
2. **Validation & tool‑args**
   - `normalize_plan` → `validate_plan`.
   - `_tool_args_from_plan` and `validate_tool_args`.
   - If plan or tool args are invalid, return blocked result with reasons.
3. **Tier split**
   - If `request_type == "baseline_free_tier"` → Baseline executor (`execute_baseline_workflow`).
   - Else → Full executor inside `run_agent`.
4. **Execution**
   - **Baseline**:
     - Runs Baseline tools in a structured registry.
     - Invokes Baseline synthesis LLM (or deterministic fallback).
   - **Full**:
     - Resolves coordinates (or uses provided ones).
     - Performs California scope check.
     - Optionally calls Earth Engine–based NDVI tool.
     - Derives fuel classification.
     - Populates placeholders for slope, proximity, photo analysis.
     - Calls CAL FIRE–aligned recommendation LLM and final reporter.
5. **Response**
   - Returns a JSON object with:
     - `plan`
     - `tool_args`
     - `validation`
     - `execution`
     - `baseline_workflow` (for Baseline flows)
     - `final_response` (narrative or structured summary text).

For a more detailed walkthrough, see `docs/architecture_v1.md` and `docs/repo_structure_and_code_guide_v1.md`.

### 5. Repository structure (Version One)

A more complete documentation of the repository layout and code roles is in `docs/repo_structure_and_code_guide_v1.md`. At a glance:

- `web_app.py` – Flask app, UI template, and HTTP API endpoints.
- `index.html` – optional static frontend (for GitHub Pages / static hosting), wired to the same API shape.
- `demo.py` – CLI wrapper that calls `run_agent` on example prompts.
- `src/`:
  - `agent.py` – main structured agent pipeline (planner, validators, Baseline/Full executors, reporters).
  - `baseline_tools.py` – Baseline tier tools (location resolution, California scope check, hazard, terrain, vegetation, and Baseline report synthesis).
  - `baseline_executor.py` – Baseline orchestration and synthesis glue.
  - `llm_client.py` – lightweight OpenAI Chat Completions client for JSON and text.
  - `prompts.py` – system prompts and templates for planner, Baseline synthesis, CAL FIRE–aligned recommendations, and reporter.
  - `tools.py` – geocoding (`geocode_google`), NDVI computation (`compute_mean_ndvi` via Earth Engine when configured), and NDVI‑based fuel classification.
  - `validators.py` – strict normalization and validation for planner outputs, tool args, and coordinates.
  - `schemas.py` – dataclasses for the execution spec, Baseline tooling context, and legacy structures.
  - `__init__.py` – package marker.
- `tests/`:
  - `test_agent.py` – agent behavior, planner behavior, fallback logic, California scope rules.
  - `test_web_app.py` – API contract for `/healthz`, `/api/plan`, `/api/assess`.
  - `test_validators.py` – plan/tool‑arg/coordinate validation invariants.
  - `test_tiered_planner_scenarios.py` – scenario‑level tests for tiered planner decisions (Baseline vs Full vs unsupported).
- `docs/`:
  - Existing docs (pre‑v1): `architecture.md`, `llm_tool_sequence.md`, `validation_checks.md`, `prompt_templates.md`, `deploy_clearsafe_org.md`.
  - New **Version One** technical documentation (see below).

### 6. Current capabilities vs limitations (Version One)

#### 6.1 Implemented capabilities

- **California‑only defensible‑space / wildfire assessment framing** with explicit out‑of‑state rejection.
- **Tiered workflow**:
  - Baseline (Free Tier) – address‑level overview.
  - Full (Paid Tier) – property‑focused assessment built on Baseline context.
- **Structured agent pipeline** with:
  - execution spec planner LLM
  - strict plan and tool‑argument validators
  - Baseline executor and Full executor
  - CAL FIRE–aligned recommendation LLM and Baseline synthesis LLM.
- **Tooling**:
  - Google Geocoding (when `GOOGLE_MAPS_KEY` is provided).
  - Google Earth Engine–based NDVI and NDVI thumbnails (when `earthengine-api` is installed and authenticated).
  - Fuel classification from NDVI.
- **Validation & safety**:
  - Strict whitelist of tools and modules.
  - California bounding‑box and geocode‑metadata check.
  - Strict constraints on radii, cloud percentages, and NDVI windows.
  - Clear blocking behavior when validations fail.
- **Testing**:
  - Unit tests for agent behavior, validators, web API, and planner scenarios (see `tests/`).

#### 6.2 Known limitations and partial features

- **California focus only** – non‑California addresses are classified as unsupported.
- **No official hazard designations** – no Fire Hazard Severity Zone labels or official CAL FIRE ratings are queried or returned.
- **NDVI and Earth Engine**:
  - If Earth Engine is not installed or configured, NDVI is **unavailable** and the system records structured reasons in metadata; Full tier still runs but may show “No Data” for NDVI and fuel.
- **Slope / terrain / proximity**:
  - No DEM or ring‑analysis tooling is integrated; these appear as explicit “Not available in this build” placeholders.
- **Photo analysis**:
  - Recognized conceptually but **not implemented**; no image uploads or image models are wired in v1.
- **UI**:
  - UI text allows “US” addresses, but the backend enforces California‑only behavior; this subtle mismatch is documented as a future UX improvement.

For a detailed catalog of gaps and planned improvements, see `docs/current_tools_and_gaps_v1.md`, `docs/recommended_code_changes_v1.md`, and `docs/future_work_v1.md`.

### 7. Quickstart – local development (Version One)

**Run-from-scratch checklist (in order):**

1. **Prerequisites:** Python 3.10+, terminal in project root (folder containing `web_app.py`).
2. **Venv:** `python -m venv .venv` → activate (see 7.2) → `pip install -r requirements.txt`.
3. **Env file:** Copy `.env.example` to `.env`. Set `OPENAI_API_KEY` and `GOOGLE_MAPS_KEY` (no quotes). For NDVI in Full assessments, also set `EARTHENGINE_PROJECT=your-gcp-project-id` (create a [Google Cloud project](https://console.cloud.google.com/) and [enable Earth Engine API](https://console.cloud.google.com/apis/library/earthengine.googleapis.com) first).
4. **Earth Engine (for NDVI):** Run authentication once (see 7.2.1).
5. **Run app:** From project root with venv activated, run `python web_app.py`. Open `http://localhost:8000`.

---

#### 7.1 Prerequisites

- Python 3.10+ (tested with modern CPython)
- Terminal open in the **project root** (the folder that contains `web_app.py`, `requirements.txt`, and `.env.example`)

#### 7.2 Install dependencies

Create a virtual environment and install into it (avoids permission errors on Windows). From the project root:

```bash
python -m venv .venv
```

Activate it, then install:

- **Linux/macOS:** `source .venv/bin/activate`
- **Windows PowerShell:** `& .\.venv\Scripts\Activate.ps1`  
  (If you get “cannot be loaded because running scripts is disabled”, run once: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.)
- **Windows CMD:** `.\.venv\Scripts\activate.bat`

Confirm the prompt shows `(.venv)`, then:

```bash
pip install -r requirements.txt
```

**Windows:** If you get `ERROR: Could not install packages due to an OSError: [WinError 2]` or `pyrsa-decrypt.exe.deleteme`, the venv is not active. Activate it again and re-run `pip install -r requirements.txt`.

#### 7.2.1 Earth Engine (for NDVI in Full assessment)

The app uses Google Earth Engine for property-level NDVI in **Full** assessments. After installing dependencies, authenticate once (with the venv activated so the `earthengine` command is available):

```bash
earthengine authenticate
```

**Windows:** If the venv is activated, `earthengine` runs from `.venv\Scripts`. If you get “No module named earthengine” when using `python -m earthengine`, run the venv’s script directly:

```powershell
.\.venv\Scripts\earthengine.exe authenticate
```

A browser window will open; sign in with your Google account and allow access. Credentials are stored locally. If you skip this step, Full assessments will still run but NDVI will show as “Not available” with a short reason in the UI.

If you see a permission or “no project” error for Earth Engine, set your Google Cloud project in `.env`: create a [Google Cloud project](https://console.cloud.google.com/), enable the [Earth Engine API](https://console.cloud.google.com/apis/library/earthengine.googleapis.com), then add `EARTHENGINE_PROJECT=your-project-id` to `.env` (see 7.3) and restart the app. Doing this before first run avoids permission errors.

#### 7.3 Environment setup

Copy the example env file. From the project root: **Linux/macOS** `cp .env.example .env` — **Windows** `copy .env.example .env`. Then edit `.env` and set:

- `OPENAI_API_KEY` (required) – LLM steps; get a key from the OpenAI dashboard.
- `GOOGLE_MAPS_KEY` (required for map/geocode) – Google Maps Geocoding and Places.
- `EARTHENGINE_PROJECT` (for NDVI) – your Google Cloud project ID with Earth Engine API enabled.

**Important (avoids "401 Unauthorized"):**

- **Do not wrap values in quotes** in `.env`. Use `OPENAI_API_KEY=sk-proj-...` not `OPENAI_API_KEY="sk-proj-..."`. Quotes become part of the value and the API will reject the key.
- **Run the app from the project root** (the folder that contains `web_app.py` and `.env`). For example: `cd DefensibleSpaceAgent` then `python web_app.py`. If you run from another directory, the app may not find `.env` and will fall back to system environment variables.
- If you have an old or invalid `OPENAI_API_KEY` in your system or user environment, the project’s `.env` is loaded with override so the key in this repo wins.

Without these keys:

- The system relies on robust deterministic fallbacks where implemented (planner, validators, Baseline synthesis, recommendations).
- Some features (e.g., NDVI via Earth Engine, live geocoding, CAL FIRE–aligned recommendations) may be unavailable or degraded; see `docs/version_one_scope_and_limitations.md`.

#### 7.4 Run the web UI

From the project root with the venv activated:

```bash
python web_app.py
```

Then open **http://localhost:8000** in your browser.

- Enter a (California) address.
- Choose **Baseline** (free) or **Full** (paid) assessment type.
- Click **Run planner** to view the planner’s explanation and execution spec.
- Click **Analyze Fire Risk** to run the full agent pipeline and see structured results.

#### 7.5 Run the CLI examples

```bash
python demo.py
```

This script runs `run_agent` against several example requests and prints the full structured JSON outputs.

#### 7.6 Run tests

```bash
pytest
```

See `docs/testing_and_validation_v1.md` for a detailed overview of testing and validation in Version One.

#### 7.7 Troubleshooting (quickstart)

- **401 Unauthorized:** Ensure `.env` has no quotes around `OPENAI_API_KEY` (e.g. `OPENAI_API_KEY=sk-proj-...` not `"sk-proj-..."`). Restart the app after editing `.env`.
- **Run from project root:** Always `cd` to the folder that contains `web_app.py` and `.env` before running `python web_app.py`.
- **Windows venv:** Use `& .\.venv\Scripts\Activate.ps1` to activate; confirm `(.venv)` in the prompt before `pip install`. If install fails with WinError 2, close other terminals and try again with venv active.
- **Earth Engine / NDVI:** Run `.\.venv\Scripts\earthengine.exe authenticate` (Windows) or `earthengine authenticate` (Linux/macOS with venv active). Then set `EARTHENGINE_PROJECT=your-gcp-project-id` in `.env` (create a Google Cloud project and enable Earth Engine API first). Restart the app.

### 8. Documentation index (Version One)

Key Version One documentation files (all under `docs/`):

- **One‑page overview**
  - `docs/one_page_proposal_v1.md`
- **Requirements & design**
  - `docs/system_requirements_specification_v1.md`
  - `docs/software_design_description_v1.md`
  - `docs/architecture_v1.md`
  - `docs/uml_v1.md`
  - `docs/flowcharts_v1.md`
- **Implementation‑oriented documentation**
  - `docs/repo_structure_and_code_guide_v1.md` (recommended first stop for code review)
  - `docs/current_tools_and_gaps_v1.md`
  - `docs/recommended_code_changes_v1.md`
  - `docs/testing_and_validation_v1.md`
  - `docs/setup_and_run_v1.md`
  - `docs/secrets_and_configuration_v1.md`
- **Framing and scope**
  - `docs/version_one_scope_and_limitations.md`
  - `docs/software_engineering_principles_v1.md`
  - `docs/mission_alignment_v1.md`
  - `docs/future_work_v1.md`
  - `docs/generative_ai_usage_disclosure_v1.md`

Legacy / pre‑v1 docs:

- `docs/architecture.md`
- `docs/llm_tool_sequence.md`
- `docs/validation_checks.md`
- `docs/prompt_templates.md`
- `docs/deploy_clearsafe_org.md`

These older files remain for historical context but may not describe the full Version One architecture; where there is any discrepancy, the **v1‑suffixed documentation** and current code should be treated as the source of truth.

### 9. Relationship to Sierra Land Management and ClearSafe California

This project is intended as a **graduate‑level software engineering and agentic AI prototype** that could evolve into part of a broader wildfire mitigation and homeowner guidance ecosystem for:

- **Sierra Land Management (SLM)** – as a technical exploration of how structured agents and remote‑sensing tools might support consulting, analyses, or field work in the Sierra Nevada and similar regions.
- **ClearSafe / ClearSafe California** – as an early prototype of a **California‑only defensible‑space and wildfire property assessment tool** that can:
  - explain wildfire context in homeowner‑friendly terms,
  - connect recommendations to CAL FIRE–aligned concepts, and
  - make limitations and uncertainty explicit.

The current Version One implementation focuses on:

- building a credible structured agent pipeline,
- clearly separating Baseline vs Full tiers,
- modeling data and validation flows, and
- documenting technical debt and future work so the system can be extended in later research or product iterations.

### 10. Disclaimers and scope boundaries

- **California‑only**: This system is intended only for California properties and locations. Requests clearly outside California are classified as unsupported.
- **Not an official inspection**: Outputs are informational and **do not** constitute CAL FIRE, local‑agency, insurance, or code‑enforcement determinations.
- **Data limitations**:
  - Earth Engine NDVI and any other remote sensing inputs are subject to data availability, cloud cover, and configuration.
  - Hazard, terrain, and vegetation context in Baseline tier are intentionally coarse and not parcel‑level.
- **No legal or insurance advice**: Nothing in this repository should be interpreted as legal, regulatory, or insurance advice.
- **Version One only**: Some capabilities are partial, placeholder, or planned; they are labeled as such in the documentation and never presented as fully implemented.

For a detailed treatment of scope and boundaries, see `docs/version_one_scope_and_limitations.md` and `docs/mission_alignment_v1.md`.
