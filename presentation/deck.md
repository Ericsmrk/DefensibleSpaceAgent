---
marp: true
title: "ClearSafe California — Defensible Space Agent (v1)"
description: "Structured, tiered multi-LLM + tools prototype for California-only wildfire defensible-space guidance."
theme: default
paginate: true
size: 16:9
---

<!-- _class: lead -->
## ClearSafe California — Defensible Space Agent (v1)

**California-only** wildfire defensible-space and property assessment agent  
**Structured planner → validators → tools → report** (Baseline vs Full tiers)

Presenter: **Eric Smrkovsky**  
Context: **CSci 264 — Fresno State**

---

## Problem & Domain Overview

**Problem**: Homeowners need understandable, actionable defensible-space guidance, but property conditions + data availability vary and “official” designations aren’t always accessible in a lightweight prototype.

**Domain (current scope)**: **California-only** wildfire defensible-space / wildfire property assessment.

**Why an agent system?**
- **Tiering**: separate “address-level baseline” from “property-focused” analysis.
- **Structured reasoning**: plan + validate before calling tools/LLMs.
- **Explicit limits**: block out-of-scope locations; degrade gracefully when data/tools are unavailable.

---

## Project Goals & Scope (v1)

- **Goal (implemented)**: Provide a **tiered** California wildfire defensible-space assessment through a single web UI + JSON APIs.
- **Baseline (Free Tier, implemented)**: address-level overview using **coarse** hazard/terrain/vegetation context + structured Baseline report JSON.
- **Full (Paid Tier, implemented)**: builds on baseline context, optionally adds **Earth Engine NDVI** + fuel class, then generates **CAL FIRE–aligned** structured recommendations + narrative.

**Out of scope / not implemented (v1)**
- Official hazard designations (e.g., **Fire Hazard Severity Zone labels**)
- Parcel boundary data, DEM-based slope, vegetation ring/proximity analytics
- Uploaded photo analysis (placeholder only when requested in plan)

---

## Agent Architecture (v1)

![Architecture overview](assets/architecture_v1.svg)

**Key components (from code)**
- **Web app**: `web_app.py` (Flask UI + `/api/plan`, `/api/assess`, `/api/geocode`, `/api/joke`)
- **Structured agent**: `src/agent.py` (planner, normalization/validation, tier split, execution, reporting)
- **Baseline executor/tools**: `src/baseline_executor.py`, `src/baseline_tools.py` (tool registry + synthesis)
- **Tools**: `src/tools.py` (Google Geocoding, Earth Engine NDVI, NDVI → fuel class)
- **Validators**: `src/validators.py` (schema + invariants + constraints)

---

## End-to-End Flow (Input → Output)

![End-to-end flow](assets/end_to_end_flow_v1.svg)

**What the system returns**
- `plan`: execution spec JSON (tier, steps, constraints)
- `tool_args`: derived args (address, buffer, date window, cloud %)
- `validation`: pass/fail + reasons
- `execution`: evidence objects (coords, NDVI meta, fuel class, placeholders)
- `baseline_workflow` (Baseline tier only): tool-by-tool outputs + Baseline report JSON
- `final_response`: narrative text (or Baseline plaintext synthesized from Baseline report)

---

## Multi-LLM Call Flow / Reasoning Flow (Conceptual)

![LLM call flow](assets/llm_call_flow_v1.svg)

**LLM roles used in v1 (from `src/prompts.py` and call sites)**
- **Planner**: produce a strict execution spec JSON (fallback spec when unavailable)
- **Validator (LLM)**: optional approval stage for non-Baseline flows (skipped under time budget)
- **Baseline synthesis**: structured Baseline report JSON from Baseline tool outputs
- **CAL FIRE recommendation**: structured mitigation plan JSON (repair attempt on malformed output)
- **Generator**: homeowner-readable narrative from plan + execution evidence

---

## Tools, APIs, and Validation (What’s actually used)

![Tools and guardrails](assets/tools_validation_v1.svg)

**External services (optional by configuration)**
- **OpenAI Chat Completions** (via `src/llm_client.py`)
- **Google Geocoding API** (via `src/tools.py: geocode_google`, requires `GOOGLE_MAPS_KEY`)
- **Google Earth Engine (Sentinel‑2 NDVI)** (via `src/tools.py: compute_mean_ndvi`, optional; returns `thumb_url` when available)

**Guardrails (implemented)**
- **California-only enforcement** (coarse bounding box; Baseline also uses geocode state metadata when present)
- **Strict plan validation**: whitelisted tools/modules, step ordering/dependencies, tier-specific constraints
- **Tool-arg validation**: numeric ranges (`buffer_m` 1..500, `cloud_pct` 0..100), NDVI window required when NDVI step present
- **Graceful degradation**: fallbacks and “not available in this build” placeholders

---

## Demo Highlights (What to show)

**Existing screenshots (repo evidence)**
- `docs/example_interaction_picture_1.PNG`
- `docs/example_interaction_picture_2.PNG`
- `docs/example_interaction_picture_3.PNG`

**Suggested live demo beats**
- Choose a California address → run **planner** (`/api/plan`) and show the execution spec + summary.
- Run **Baseline** assessment and show the structured Baseline report sections rendered.
- Run **Full** assessment:
  - show NDVI + fuel class when Earth Engine is configured,
  - show “Not available” evidence when it isn’t (same UX, explicit reasons),
  - expand “View full structured output” to highlight plan/validation/execution objects.

*(If you want additional screenshots beyond those in `docs/`, see `presentation/recommendations.md` for exact capture targets.)*

---

## Key Technical Challenges & Solutions (From the implementation)

<!-- style: font-size: 26px; -->
- **Safe, predictable LLM output**: execution‑spec JSON + strict validators/tool whitelist (`src/validators.py`).
- **Optional tools/data**: explicit evidence metadata + graceful “unavailable” fallbacks (geocode/NDVI).
- **Latency/timeouts**: budget-aware skipping of noncritical calls (validator/NDVI/narrative) in `run_agent`.
- **UI scope mismatch** (**US** text vs **CA-only** backend): backend blocks out‑of‑CA; **future work** to align UI copy/restrictions.

---

## Lessons Learned & Future Directions

**Lessons learned (v1)**
- Tiering + explicit validation makes agent behavior easier to reason about and test.
- Fallback paths are essential for demos and reliability when APIs are missing/unavailable.
- Structured outputs (`plan`, `validation`, `execution`) improve debuggability and UX transparency.

**Future directions (not yet implemented)**
- Integrate **official hazard layers** (clearly labeled provenance) and/or recent fire perimeter datasets.
- Replace placeholders with real modules: **DEM-based slope**, vegetation proximity/rings, parcel boundary integration.
- Implement real **photo ingestion + analysis** (with explicit safety constraints and opt-in).
- UX alignment: California-only address restriction in the UI, clearer tier explanations, faster “baseline-first” defaults.

