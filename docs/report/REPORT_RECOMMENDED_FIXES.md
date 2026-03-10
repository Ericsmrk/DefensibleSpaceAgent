## Report audit recommendations (based on current repo)

This file documents **mismatches, gaps, and recommended fixes** found while producing the course PDF report from the repository as the source of truth. It does **not** change application logic.

### A. Documentation mismatches vs. current implementation
- **Legacy “Generator (LLM) → tool args JSON” stage is no longer implemented**
  - **Docs claiming it exists**: `docs/architecture.md`, `docs/llm_tool_sequence.md`, `docs/prompt_templates.md`, and `PROJECT_STATE_AND_FLOW.md` describe an LLM “generator” that produces tool-argument JSON.
  - **Current code**: `src/agent.py` derives `tool_args` deterministically from the validated plan constraints and context; there is **no LLM generator call** for tool args in Version One.
  - **Recommendation**: Update the legacy docs (or add a short “Version One update” note) to reflect the current pipeline: planner (LLM) → rule validators → deterministic tool args → (Full tier) validator LLM → execution.

- **`PROJECT_STATE_AND_FLOW.md` appears to be an older snapshot**
  - The file header says “Last updated: March 7, 2025” and describes behaviors (e.g., NDVI mocked, UI planner prompt usage) that do not fully match the current Version One tiered Baseline executor and Earth Engine NDVI integration.
  - **Recommendation**: Either (1) update this snapshot to Version One, or (2) label it clearly as historical and point readers to `README.md` + `src/` as authoritative.

- **README’s “Version One documentation index” references files that are not present**
  - `README.md` lists multiple `docs/*_v1.md` files (e.g., `docs/architecture_v1.md`, `docs/testing_and_validation_v1.md`, etc.) that are **not currently in `docs/`** in this repository snapshot.
  - **Recommendation**: Remove/repair broken links, or re-add the missing v1 docs if they exist elsewhere.

### B. UI/UX messaging mismatch vs. backend policy
- **UI states “US address” while backend is California-only**
  - `web_app.py` UI copy says “property in the US” and restricts autocomplete to US addresses.
  - Backend planning + validation enforces California-only support and blocks out-of-state coordinates/requests.
  - **Recommendation**: Update UI copy to “California addresses only” and optionally restrict Places suggestions to California if desired.

### C. External dependency assumptions to clarify
- **NDVI requires Earth Engine authentication**
  - `earthengine-api` is present in `requirements.txt`, but Full-tier NDVI depends on local credentials (`earthengine authenticate`) and a valid project configuration (`EARTHENGINE_PROJECT` in some environments).
  - **Recommendation**: Add a short “NDVI availability matrix” section to README or docs explaining the exact behavior when Earth Engine is missing vs. authenticated.

- **Geocoding is disabled without `GOOGLE_MAPS_KEY`**
  - `src/tools.py:geocode_google()` returns `None` coordinates with a structured error when `GOOGLE_MAPS_KEY` is missing (it does not fabricate coordinates).
  - **Recommendation**: Ensure docs/examples clearly state that address-only execution requires geocoding; otherwise the UI should encourage providing/using coordinates from Places selection.

### D. “Implemented vs placeholder” items to keep explicit
- **Placeholders in Full tier**: slope analysis, vegetation proximity, and uploaded photo analysis are present as explicit “Not available” / placeholder outputs.
  - **Recommendation**: Keep these labeled as “not implemented” in docs and in the UI (already largely done), and consider adding tests that assert these placeholders remain non-claiming and safe.

### E. Testing/documentation alignment improvements (non-breaking)
- Add/expand tests for Baseline executor outputs (`src/baseline_executor.py`) and Baseline synthesis fallback behavior when `OPENAI_API_KEY` is missing.
- Add a small “API contract” doc section describing the key response fields returned by `/api/plan` and `/api/assess` (plan/tool_args/validation/execution/baseline_workflow).

