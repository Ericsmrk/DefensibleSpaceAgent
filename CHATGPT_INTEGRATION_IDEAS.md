# ChatGPT Integration Brainstorm for Defensible Space Agent

## 1) Recommended Domain Choice
Given your current notebook (geocoding + NDVI + fuel classification), your best fit is likely:

- **Other Instructor-Approved Domain**: *Wildfire Defensible-Space Assessment Agent*

Why this is strong:
- You already have real tool calls (Google Geocoding + Earth Engine).
- You can clearly demonstrate **planner → generator → validator → executor**.
- Produces concrete artifacts (risk JSON + homeowner action plan + map snapshot).

---

## 2) “Structured Agent” Architecture (mapped to assignment language)
Use 4 explicit modules:

1. **Planner (LLM Call #1)**
   - Input: user goal (e.g., “Assess my property fire risk and recommend mitigation”).
   - Output: strict JSON plan with steps, required tools, and constraints.

2. **Generator (LLM Call #2)**
   - Converts plan into tool-ready arguments.
   - Example outputs:
     - normalized address
     - AOI buffer sizes
     - date windows
     - expected output schema

3. **Validator (LLM Call #3 + rule-based checks)**
   - LLM checks coherence/completeness of plan and outputs.
   - Rule-based checks enforce hard constraints (allowed tools only, lat/lon bounds, max buffer radius, required JSON keys).

4. **Executor (Tool layer, non-LLM)**
   - Runs geocoder, Earth Engine NDVI pipeline, optional weather/fuel overlays.
   - Returns structured result for final response generation.

5. **Reporter/Summarizer (LLM Call #4)**
   - Produces user-friendly explanation + prioritized defensible-space actions.
   - Can be tailored to homeowner vs. analyst style.

---

## 3) Minimal Multi-LLM Flow You Can Demo
For each user request:

- **Call A (Planner):** produce plan JSON.
- **Validate A:** schema + policy checks.
- **Call B (Tool-Arg Generator):** produce exact tool args.
- **Validate B:** argument checks (ranges, required fields).
- **Tool execution:** geocode + NDVI compute.
- **Call C (Result Validator):** sanity-check result interpretation.
- **Call D (Final Writer):** concise recommendation report.

This gives you a clear “multiple LLM calls + tools + validation” story.

---

## 4) Concrete ChatGPT API Integration Pattern
Use OpenAI Chat Completions (or Responses API) with **JSON outputs** for intermediate steps.

### Suggested prompt roles
- **System (Planner):** “You are a strict planning agent. Output JSON only.”
- **System (Generator):** “Map plan to tool arguments. Output JSON only.”
- **System (Validator):** “Check policy and schema compliance; output pass/fail + reasons.”
- **System (Reporter):** “Write actionable wildfire mitigation guidance based on structured results.”

### Data contracts (important for grading)
Define schemas like:
- `PlanSchema`
- `ToolArgsSchema`
- `ExecutionResultSchema`
- `ValidationReportSchema`

Your report can emphasize that **intermediate representations are machine-readable JSON**.

---

## 5) Validation & Safety Checks (high-value grading section)
Add both rule-based and LLM-based validation.

### Rule-based (hard constraints)
- Allowed tools: `{geocode_google, compute_mean_ndvi, classify_fuel}`.
- Disallow arbitrary code execution.
- Latitude range `[-90, 90]`, longitude range `[-180, 180]`.
- Buffer limit (e.g., `<= 500m`) to avoid expensive requests.
- Required keys in all intermediate JSON.
- Timeout + retry policy for API calls.

### LLM-based (soft checks)
- Detect contradictory recommendations.
- Ensure recommendations cite evidence fields (`mean_ndvi`, `fuel_class`, maybe slope/wind if added).

---

## 6) Three Example Interactions (for repo requirement)
Create at least 3 end-to-end examples in notebook/script:

1. **Single residential address** (happy path).
2. **Ambiguous address** (validator asks for clarification or uses best-match with confidence warning).
3. **Low/No data scenario** (cloud cover/high uncertainty), with graceful fallback output.

---

## 7) Suggested Repo Structure

```
project-root/
  README.md
  demo.ipynb
  src/
    agent.py                # orchestrator
    llm_client.py           # ChatGPT wrappers
    tools.py                # geocode + ee compute
    validators.py           # schema + policy checks
    prompts.py              # planner/generator/validator/reporter templates
    schemas.py              # pydantic/json schema models
  docs/
    architecture.md
    llm_tool_sequence.md
    prompt_templates.md
    validation_checks.md
  tests/
    test_validators.py
    test_schema_contracts.py
```

---

## 8) Deliverable Mapping (quick checklist)

### Report (5–8 pages)
- Problem + why defensible-space automation matters.
- Architecture diagram with 4+ modules.
- Multi-call flow with sample JSON.
- Tool/API details (OpenAI + Google + Earth Engine).
- Validation/safety section with concrete rules.
- Results + failure modes.

### GitHub repo
- `README` with run instructions and secret handling.
- Demo notebook with 3 example interactions.
- Prompt templates + validation docs.
- Simple tests/assertions for constraints.

### Slides (6–10)
- 1: problem
- 2: architecture
- 3: call sequence
- 4: demo outputs
- 5: validation/safety
- 6: lessons/future work

---

## 9) Fast MVP Plan (what to build next in order)
1. Wrap your existing notebook logic into callable Python functions.
2. Add one orchestrator function: `run_agent(user_request)`.
3. Add 3–4 ChatGPT calls with strict JSON outputs.
4. Add validators + tests for argument constraints.
5. Add 3 scripted demo scenarios.
6. Write docs and slides from the same architecture.

---

## 10) Optional Stretch Features (if time)
- Multi-property batch assessment.
- Confidence score + uncertainty explanation.
- Versioned recommendations by season.
- GitHub Action to run demo tests on push.
