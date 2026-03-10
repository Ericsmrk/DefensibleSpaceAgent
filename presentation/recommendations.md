## Recommendations / discrepancies found while building the deck

This file documents (a) anything that looked inconsistent across docs vs code, (b) missing assets that would strengthen the demo slide, and (c) suggested next captures for a polished presentation.

### Confirmed implementation facts (used in slides)
- **Tiered agent**: `baseline_free_tier` vs `full_paid_tier` is implemented in `src/agent.py` with a hard tier split.
- **Baseline executor exists**: `src/baseline_executor.py` orchestrates `src/baseline_tools.py` and produces a structured Baseline report JSON (`baseline_workflow.final_report`).
- **Google Geocoding is real (when configured)**: `src/tools.py: geocode_google` calls Google Geocoding API; returns `(None, None, meta)` when `GOOGLE_MAPS_KEY` is missing.
- **Earth Engine NDVI is real (when configured)**: `src/tools.py: compute_mean_ndvi` uses Google Earth Engine Sentinel‑2 and may return a `thumb_url`.
- **Validation is strict**: `src/validators.py` enforces canonical plan schema, whitelisted tools/modules, step ordering, tier-specific tool requirements, and constraints ranges.
- **California-only is enforced**:
  - Baseline: bounding box + geocode metadata check (`src/baseline_tools.py: validate_california_scope`)
  - Full: bounding box safety check during execution (`src/agent.py`)
- **Placeholders are explicit in Full tier**: slope / vegetation proximity / photo analysis are “Not available in this build” placeholders in `src/agent.py`.

### Discrepancies / potential confusion points
- **`PROJECT_STATE_AND_FLOW.md` is partially outdated** relative to current code:
  - It describes a “generator (LLM) tool-args JSON” stage and “mock NDVI”; current `src/agent.py` derives `tool_args` deterministically and uses Earth Engine (optional) for NDVI.
  - It says `/api/plan` is a single text LLM call; current `/api/plan` calls `src.agent.run_planner_only` (JSON planner) and returns `planner_summary` (the UI still has a separate long text prompt embedded in `web_app.py`, but it is not the runtime planner inside `src/agent.py`).
- **README references v1 docs that are not present in `docs/`** in this repo snapshot (e.g., `docs/architecture_v1.md`, `docs/flowcharts_v1.md`, `docs/future_work_v1.md`, etc.). The deck avoids citing those missing files.
- **UI wording vs backend scope**:
  - UI copy and autocomplete restrictions are “US” (`componentRestrictions: { country: 'us' }`), but the backend enforces **California-only**.

### Missing demo assets (not fabricated)
The repo contains three interaction screenshots in `docs/`:
- `docs/example_interaction_picture_1.PNG`
- `docs/example_interaction_picture_2.PNG`
- `docs/example_interaction_picture_3.PNG`

For a stronger “Demo Highlights” slide, capture these additional screenshots (optional):
- **Planner JSON**: After clicking “Run planner”, expand the “JSON” details.
- **Baseline render**: Run a Baseline assessment and capture the rendered sections (Summary + scope validation + hazard/terrain/vegetation + limitations).
- **Full render with NDVI available**: Show the NDVI thumbnail map (requires Earth Engine auth) and the fuel class.
- **Full render with NDVI unavailable**: Show the UI state where NDVI is “Not available” and the reason is displayed.
- **Structured output**: Expand “View full structured output” on the assessment result.

### Presentation editability recommendations
- If you prefer PowerPoint: export `presentation/deck.md` using a tool like Marp (Markdown → PPTX), then edit in PowerPoint/Google Slides.
- Keep the SVG diagrams in `presentation/assets/` as the single source of truth; they are easy to tweak later (box labels match the code).

