## Speaker notes — ClearSafe California / Defensible Space Agent (v1)

### Slide 1 — Title
- One-liner: tiered California-only wildfire defensible-space agent.
- Emphasize: structured pipeline, not a monolithic chat.

### Slide 2 — Problem & domain
- Pain point: homeowners want guidance; data is uneven; “official” layers aren’t integrated in v1.
- Why agents: tiering + validation + explicit limits.

### Slide 3 — Goals & scope
- Baseline vs Full: what each includes.
- Call out what is intentionally omitted (official ratings, parcel-level analytics).
- Keep “not implemented” items clearly separated.

### Slide 4 — Architecture
- Walk through modules: UI/API → agent → validators → tools → reporting.
- Mention Baseline has its own executor + tool registry + synthesis.

### Slide 5 — End-to-end flow
- Start at `/api/assess`: planner emits steps, validators gate, tier split, execution, response object.
- Highlight: structured `plan`, `validation`, `execution`, `final_response`.

### Slide 6 — Multi-LLM reasoning flow
- Planner = execution spec; validator LLM = optional approval; synthesis/recommendations = structured JSON.
- Note time-budgeting: some calls can be skipped under tight budgets.

### Slide 7 — Tools/APIs/validation
- Tools are optional and degrade gracefully:
  - Geocoding requires `GOOGLE_MAPS_KEY`.
  - NDVI requires Earth Engine auth + `earthengine-api`.
- Guardrails: tool whitelist, constraints ranges, California-only checks.

### Slide 8 — Demo highlights
- Plan-first: show `/api/plan` and the execution spec.
- Baseline run: show report sections.
- Full run: show NDVI map thumbnail if configured; otherwise show explicit “Not available” reason.
- Expand debug JSON to demonstrate transparency.

### Slide 9 — Challenges & solutions
- Reliability: strict validation + fallbacks.
- Optional data: evidence metadata + placeholders.
- Timeouts: budget-aware skipping.
- UX mismatch: US wording vs CA-only enforcement (future fix).

### Slide 10 — Lessons & future
- What worked: structured outputs, tiering, validation.
- Next steps: official layers, slope/proximity, photo analysis, UI alignment, stronger typing.

