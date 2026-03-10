### Repo Structure and Code Guide – Version One

**File**: `docs/repo_structure_and_code_guide_v1.md`  
**Scope**: Version One (`v1`) of the ClearSafe California – Defensible Space Agent  
**Audience**: Future you, code reviewers, and graduate‑level technical readers preparing for a code‑commenting and code‑review pass.

---

### 1. How to use this guide

This guide is meant to be the **primary on‑ramp** to understanding the codebase. It explains:

- **Top‑level repository map**
- **Roles of key modules and files**
- **Where orchestration vs. tools vs. prompts vs. UI live**
- **How data and control flow through the system**
- **Suggested reading order for a deep review**
- **Where future comments and refactors are likely to pay off**

It intentionally focuses on **Version One** behavior as reflected in the current repository. When earlier documentation disagrees with this file, **treat the code and this document as the source of truth**.

---

### 2. Top‑level layout (Version One)

At the repo root:

- `web_app.py` – Flask application that:
  - embeds the ClearSafe UI (single‑page HTML) as a large `INDEX_HTML` string,
  - wires HTTP routes (`/`, `/api/plan`, `/api/assess`, `/api/geocode`, `/api/joke`, `/healthz`, `/version`),
  - adapts the UI contract to the agent and tool layers in `src/`.
- `index.html` – Standalone static page closely mirroring the inline UI in `web_app.py`; useful for GitHub Pages and static hosting.
- `requirements.txt` – Core Python dependencies (Flask, python‑dotenv, pytest, earthengine‑api).
- `.env.example` – Template for local env: `OPENAI_API_KEY`, `GOOGLE_MAPS_KEY`, optional `EARTHENGINE_PROJECT` (copy to `.env`).
- `render.yaml`, `Procfile`, `runtime.txt` – Deployment descriptors (e.g., Render / Heroku‑style).
- `tests/` – Pytest suite for the agent, web app, validators, and tiered planner scenarios.
- `src/` – All agent logic, tools, validators, prompts, and schemas.
- `docs/` – Human‑readable documentation, including this file and other Version One design/architecture docs.

Supporting design docs at the root:

- `PROJECT_STATE_AND_FLOW.md` – Earlier snapshot of the architecture and data flow.
- `CHATGPT_INTEGRATION_IDEAS.md` – Early ideation around structured agents and ChatGPT integration.

Both are useful historical artifacts but partially predate the current Baseline/Full implementation and Baseline executor.

---

### 3. `src/` package – where core logic lives

The `src/` directory contains the structured agent, Baseline executor, tools, validators, prompts, and schemas. It is the **center of gravity** for Version One.

#### 3.1 `src/agent.py` – structured agent orchestration

**Role**: Main orchestrator for the tiered agent pipeline.

Key responsibilities:

- Build **planner context** from:
  - user request text,
  - optional address and coordinates,
  - tier preference (`baseline_free_tier` vs `full_paid_tier`),
  - optional photo flags.
- Run the **planner LLM** (`run_planner_only`) and apply a robust `_fallback_execution_spec` when LLMs are not available or invalid.
- Normalize and validate planner output via:
  - `normalize_plan` (schema normalization and legacy compatibility),
  - `validate_plan` (strict structural and semantic checks).
- Derive and validate **tool arguments** (`_tool_args_from_plan`, `_fallback_tool_args`, `validate_tool_args`).
- Split the pipeline by **tier**:
  - Baseline → `execute_baseline_workflow` in `baseline_executor.py`.
  - Full → in‑file executor that iterates planner steps and calls internal tools from `tools.py`.
- For Full tier, call:
  - `CALFIRE_RECOMMENDATION_SYSTEM` for structured, CAL FIRE–aligned recommendations,
  - `GENERATOR_SYSTEM` for homeowner‑readable narrative.
- Pack the final structured response for `/api/assess` (plan, tool_args, validation, execution, baseline_workflow, final_response).

Functions to pay special attention to in a future commenting/review pass:

- `_fallback_execution_spec(...)` – Encodes the baseline vs full classification, incomplete/unsupported rules, and default analysis modules/steps.
- `run_planner_only(...)` – LLM + fallback planner front‑end with schema normalization.
- `run_agent(...)` – Full end‑to‑end orchestrator; central to understanding control flow and failure modes.

These are high‑leverage places for **careful comments** (e.g., design rationale, safety constraints, and invariants).

#### 3.2 `src/baseline_tools.py` – Baseline tool implementations

**Role**: Implements the Baseline (Free Tier) tool layer used by the dedicated Baseline executor.

Key functions:

- `resolve_location(context)` – Uses provided coordinates if available, otherwise geocodes the address with `geocode_google` from `tools.py`. Updates `BaselineToolContext`.
- `validate_california_scope(context)` – Confirms that the location appears to be in California using a bounding‑box check and lightweight geocode metadata.
- `gather_hazard_context(context)` – Produces **coarse** regional wildfire hazard context; explicitly does **not** assign parcel‑level ratings.
- `gather_terrain_context(context)` – Qualitative description of terrain’s role in fire behavior; no DEM or slope model.
- `gather_regional_vegetation_context(context)` – Qualitative regional vegetation/fuel discussion; no parcel fuel mapping.
- `generate_baseline_report(context, llm_client)` – Uses `BASELINE_SYNTHESIS_SYSTEM` plus deterministic fallback to create a structured Baseline report JSON.

At the bottom, `TOOL_REGISTRY` maps well‑known tool identifiers to these functions. This is the **conceptual tools layer** for Baseline workflows and is a good candidate for:

- adding richer tools in Version Two,
- injecting mocks/fakes in tests,
- documenting behavior with short, intent‑focused comments.

#### 3.3 `src/baseline_executor.py` – Baseline orchestrator

**Role**: Orchestrates Baseline tool calls and synthesis.

Core ideas:

- Builds a `BaselineToolContext` (see `schemas.py`) from:
  - address, coordinates, and planner execution spec,
  - constraints (e.g., buffer radius if needed).
- Walks the planner steps that are relevant to Baseline (`resolve_location`, California validation, hazard, terrain, regional vegetation, report synthesis).
- Accumulates `ToolResult` objects keyed by step id.
- Calls `generate_baseline_report` to produce a structured `FinalBaselineReport`.
- Returns a `BaselineOrchestratorResult` with:
  - `status` (e.g., `"completed"`),
  - `plan`,
  - `step_outputs`,
  - `final_report` (or `None` if synthesis is unavailable).

This file is the best place to understand **how Baseline is implemented as a first‑class flow**, distinct from the legacy Full executor logic inside `agent.py`.

#### 3.4 `src/tools.py` – external data tools

**Role**: Encapsulate direct calls to external services (Google Maps, Earth Engine) and local transformations.

Important functions:

- `geocode_google(address: str)`:
  - Uses `GOOGLE_MAPS_KEY` to call the Google Geocoding API.
  - Returns `(lat, lon, meta)` with:
    - `formatted_address`,
    - state/county/city metadata (for California scope checks),
    - status and error fields.
  - Returns `(None, None, {...})` with **structured error metadata** when keys are missing or the API fails.
- `compute_mean_ndvi(...)`:
  - If `earthengine-api` is not installed or cannot be initialized:
    - Returns `None` and a metadata dict explaining why NDVI is unavailable.
  - Otherwise:
    - Uses Sentinel‑2 data in Google Earth Engine to compute a mean NDVI for a buffered area around the coordinate.
    - Optionally returns a thumbnail URL for visualization in the UI.
- `classify_fuel(ndvi)`:
  - Simple rule‑based interpretation of NDVI into coarse fuel classes.

This module is the main place where **real‑world data sources touch the system**. It is a natural focus area for:

- robust error handling,
- configuration options (e.g., date windows, chosen sensor),
- performance and cost considerations.

#### 3.5 `src/validators.py` – structural & semantic validation

**Role**: Enforce invariants for planner outputs, tool arguments, and coordinates.

Key elements:

- Constant sets and maps:
  - `VALID_REQUEST_TYPES`, `VALID_ASSESSMENT_MODES`
  - `ALLOWED_TOOLS`, `ALLOWED_ANALYSIS_MODULES`
  - `ALLOWED_CONSTRAINT_KEYS`, `REQUIRED_CONSTRAINT_KEYS`
  - `LEGACY_REQUEST_TYPE_MAP`, `LEGACY_TOOL_MAP`
- `normalize_plan(plan)`:
  - Normalizes legacy shapes into canonical keys and tool names.
  - Ensures required keys exist and that `analysis_modules` use conceptual names.
  - Returns normalized plan plus reasons if anything is unexpected.
- `validate_plan(plan, provided_lat=None, provided_lng=None)`:
  - Checks:
    - top‑level keys,
    - request_type vs assessment_mode consistency,
    - `execution_ready` vs `missing_requirements`,
    - location strategy vs steps (e.g., no `resolve_location` if `use_provided_coordinates` is `True`),
    - tier‑specific tool rules (Baseline vs Full),
    - constraints ranges and allowed keys,
    - correctness of `analysis_modules`, `recommended_next_action`, `planner_summary`.
- `validate_tool_args(args, plan=...)`:
  - Enforces ranges on `buffer_m` and `cloud_pct`,
  - Checks required `start`/`end` dates when NDVI is needed,
  - Ensures `address` is present when `resolve_location` is in the steps.
- `validate_coordinates(lat, lon)`:
  - Simple bounds checks for latitude and longitude.

This module encodes a **large amount of the system’s safety and policy logic**. It is a prime candidate for:

- targeted comments about why particular invariants exist,
- cross‑referencing with design docs (SRS/SDD),
- expanding tests as new features are added.

#### 3.6 `src/prompts.py` – LLM system prompts

**Role**: Centralize system‑level instructions for the structured agent.

Main prompts:

- `PLANNER_SYSTEM`, `PLANNER_PROMPT` – drive the execution‑spec planner (JSON‑only).
- `EXECUTION_SYSTEM` – designed for a conceptual execution description layer (currently not a direct runtime dependency).
- `VALIDATOR_SYSTEM` – extremely small contract for LLM‑based validation summary.
- `BASELINE_SYNTHESIS_SYSTEM` – instructions for synthesizing a structured Baseline report from tool outputs.
- `GENERATOR_SYSTEM` – instructions for generating a homeowner‑readable narrative from plan and execution evidence.
- `CALFIRE_RECOMMENDATION_SYSTEM` – a long and carefully constrained prompt for CAL FIRE–aligned mitigation recommendations.

This file is essential to understanding the **intended semantics** of each LLM call. For a future review:

- Consider commenting the relationship between each prompt and the corresponding function(s) in `agent.py` or `baseline_tools.py`.
- Consider documenting how contracts in `VALIDATOR_SYSTEM` and `CALFIRE_RECOMMENDATION_SYSTEM` line up with expectations in `validators.py`.

#### 3.7 `src/llm_client.py` – OpenAI client wrapper

**Role**: Minimal HTTP wrapper to the OpenAI Chat Completions API.

Main methods:

- `is_configured()` – checks for `OPENAI_API_KEY`.
- `chat_json(system, user, fallback)` – JSON‑typed calls with server‑side `response_format={"type": "json_object"}`.
- `chat_text(system, user, fallback)` – text‑typed calls for narratives.

The module also encodes **fallback behavior**: when keys are absent, it simply returns the provided fallback. This is a key reason why the system can still run tests and offline demos without external connectivity.

#### 3.8 `src/schemas.py` – data classes and typed views

**Role**: Provide Python dataclasses for planner execution specs, Baseline contexts, Baseline reports, and legacy structures.

Important types:

- `ExecutionSpec`, `ExecutionStep`, `LocationStrategy`, `PlanConstraints`, `DateWindow`
- `ToolResult` – standard schema used heavily in Baseline tooling.
- `BaselineSynthesisSections`, `BaselineSynthesisEvidence`, `FinalBaselineReport`
- `BaselineToolContext`, `BaselineOrchestratorResult`
- Legacy/compat:
  - `PlanStep`, `Plan`, `ToolArgs`, `ExecutionResult`, `ValidationReport`, `AgentOutput`

While some of these are not used directly in runtime paths, they:

- document the intended shapes of various JSON structures,
- provide a useful reference for future static typing and validation,
- can serve as a base for future comment/documentation improvements.

---

### 4. `web_app.py` – UI, API surface, and integration glue

`web_app.py` stitches together the UI and the agent pipeline. It is long but conceptually segmented into:

1. **Imports and configuration**
   - Loads environment with `python-dotenv`.
   - Imports `run_agent`, `run_planner_only`, `normalize_plan_for_provided_coordinates`, `LLMClient`, and `geocode_google`.
   - Pulls in `GOOGLE_MAPS_KEY` and uses a placeholder when missing (so the UI can still load).

2. **Planner‑only UI prompt (Run planner button)**
   - Defines a **separate** `PLANNER_SYSTEM` / `PLANNER_PROMPT` pair, focused on:
     - address‑level California wildfire baseline,
     - listing next‑step options,
     - no JSON output (plain text meant for display).
   - This is intentionally different from the JSON planner in `src/prompts.py`.

3. **`INDEX_HTML` single‑page UI**
   - Large HTML + CSS + JavaScript template that:
     - handles address autocomplete and map display (via Google Maps JavaScript API),
     - manages hidden fields for `selected_address`, `selected_lat`, `selected_lng`,
     - renders planner responses and Baseline/Full assessment results,
     - includes a small “joke” panel for the `/api/joke` endpoint.
   - The UI currently mentions “US” addresses, but the backend logic is California‑only.

4. **Routes**
   - `GET /` – renders the HTML template with `google_maps_api_key` injected.
   - `POST /api/geocode` – JSON geocoding helper.
   - `POST /api/plan` – planner‑only endpoint:
     - builds a small planner context,
     - calls `run_planner_only`,
     - normalizes plans when coordinates are provided,
     - returns `{ plan, response }`, where `response` is the `planner_summary`.
   - `POST /api/joke` – uses `LLMClient` and an internal `JOKE_SYSTEM` prompt; graceful degradation when `OPENAI_API_KEY` is missing.
   - `POST /api/assess` – full assessment endpoint:
     - reads `request`, optional `address`, `lat`, `lng`, `uploaded_photos_*`,
     - logs the request,
     - maps frontend `"full"` / `"baseline"` into canonical tier names,
     - calls `run_agent(...)` with normalized arguments,
     - returns the full structured agent output.
   - `GET /healthz`, `GET /version` – basic health/version markers.

From a review perspective, `web_app.py` is a good:

- starting point to understand **how external clients are expected to call the agent**, and
- candidate for future refactoring (e.g., moving `INDEX_HTML` to a template file, decomposing HTML/JS).

---

### 5. `tests/` – what is currently exercised

The tests give a concise map of expected behaviors:

- `tests/test_agent.py`
  - Confirms that `run_agent` returns the expected top‑level keys.
  - Checks incomplete vs supported requests (e.g., missing address/coords).
  - Tests that Full tier can return NDVI and fuel class (assuming NDVI is available).
  - Verifies that provided coordinates skip geocoding and are reflected in the plan (`use_provided_coordinates`).
- `tests/test_web_app.py`
  - Verifies:
    - `/healthz` returns `{ "ok": true }`.
    - `/api/assess` enforces presence of `request`.
    - `/api/assess` returns a structured shape with `execution` and `final_response`.
    - `/api/plan` requires `address` and returns a structured `plan`/`response`.
    - `/api/plan` and `/api/assess` correctly propagate provided coordinates into planner outputs.
- `tests/test_validators.py`
  - Exercises `validate_plan`, `validate_tool_args`, `validate_coordinates` across:
    - valid and invalid request types and assessment modes,
    - dependency ordering,
    - constraints ranges (`buffer_m`, `cloud_pct`, `photo_count`),
    - location strategy vs steps,
    - “use provided coordinates” scenarios.
- `tests/test_tiered_planner_scenarios.py`
  - Scenario tests for:
    - Baseline vs Full classification,
    - use of geocoding vs provided coordinates,
    - inclusion or exclusion of photo analysis steps,
    - incomplete vs unsupported requests.

For a future code‑review pass, reading these tests side‑by‑side with `agent.py` and `validators.py` is an efficient way to reconstruct **intended behavior and invariants**.

---

### 6. Suggested reading order for a deep review

If you have limited time to reacquaint yourself with the code, consider this order:

1. **High‑level docs**
   - `README.md`
   - `docs/one_page_proposal_v1.md`
   - `docs/architecture_v1.md`
2. **Orchestration and contracts**
   - `src/agent.py`
   - `src/validators.py`
   - `src/baseline_executor.py`
3. **Tools and external integrations**
   - `src/tools.py`
   - `src/baseline_tools.py`
   - `src/llm_client.py`
4. **Prompts and semantics**
   - `src/prompts.py`
   - `web_app.py` (for the planner UI prompt and how `/api/plan` uses it)
5. **Schemas and tests**
   - `src/schemas.py`
   - `tests/` (especially `test_agent.py` and `test_tiered_planner_scenarios.py`)

This path will give you a realistic view of how Baseline and Full tiers are implemented, how California‑only rules are enforced, and where external services are used.

---

### 7. Future code‑commenting hotspots

The following areas are likely to benefit most from **clear, graduate‑level comments** in a future pass:

- `src/agent.py`
  - `_fallback_execution_spec` (tier classification and constraints)
  - `run_planner_only` (LLM+fallback behavior and normalization)
  - `run_agent` (full pipeline control flow and tier branching)
- `src/baseline_executor.py`
  - coordination between planner steps, Baseline tools, and synthesis LLM
  - how failures propagate back to `run_agent`
- `src/baseline_tools.py`
  - design intent behind each Baseline tool and how it stays safely high‑level
- `src/validators.py`
  - rationale for constraints and invariants (buffer ranges, allowed tools, analysis modules)
- `src/tools.py`
  - assumptions and safety precautions around Google Geocoding and Earth Engine
- `src/prompts.py`
  - linkage between prompt contracts and the schemas enforced elsewhere
- `web_app.py`
  - explanation of UI/UX decisions and how they map to API calls

Comments in these locations would help reviewers connect the **formal documentation** (SRS/SDD) to concrete implementation decisions.

---

### 8. Potential naming and organization improvements (documented only)

The following are **recommended code‑level improvements for future versions** (they are **not** implemented in Version One):

- Consolidate overlapping notions of “generator” vs “reporter” prompts and functions so the terminology is consistent across code, prompts, and docs.
- Rename or clearly distinguish:
  - the JSON‑producing planner in `src/prompts.py`,
  - the text‑producing planner prompt embedded in `web_app.py` (for the “Run planner” UI).
- Extract the long `INDEX_HTML` string in `web_app.py` into a template file (`templates/index.html`) or static asset to improve readability and diffability.
- Consider separating Baseline and Full flows into distinct, smaller orchestration modules or classes (e.g., `BaselineAgent`, `FullAgent`) while keeping `run_agent` as a unified entry point.
- Introduce stronger typing and/or dataclass usage at the boundary between LLM JSON and runtime dicts to minimize ad‑hoc `.get` usage.

These and other recommended changes are described in more detail in `docs/recommended_code_changes_v1.md`.

---

### 9. Summary

- The **core logic** of Version One lives in `src/` and is orchestrated by `src/agent.py`.
- **Baseline** and **Full** tiers share a common planner and validator, but diverge cleanly in execution:
  - Baseline via `baseline_executor.py` + `baseline_tools.py`.
  - Full via direct tool calls and CAL FIRE–aligned recommendations inside `agent.py`.
- The **UI and HTTP surface** are defined in `web_app.py` (and `index.html`), which map cleanly to planner‑only and full‑pipeline endpoints.
- **Validators**, **prompts**, and **schemas** capture a significant amount of the architectural intent and safety constraints.

Use this file as a compass when you come back later for deeper code review, refactoring, or comment writing.

