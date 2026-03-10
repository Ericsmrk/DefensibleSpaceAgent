## Presentation build status (v1)

### What was created
- **Editable slide source**: `presentation/deck.md` (Marp-compatible Markdown, exactly 10 slides)
- **Supporting assets** (diagrams):  
  - `presentation/assets/architecture_v1.svg`  
  - `presentation/assets/end_to_end_flow_v1.svg`  
  - `presentation/assets/llm_call_flow_v1.svg`  
  - `presentation/assets/tools_validation_v1.svg`
- **Speaker notes**: `presentation/speaker_notes.md`
- **Recommendations / discrepancies log**: `presentation/recommendations.md`

### Sources used (repo evidence)
- **Primary**: `README.md`
- **Code verification**:
  - `web_app.py`
  - `src/agent.py`
  - `src/validators.py`
  - `src/tools.py`
  - `src/baseline_executor.py`
  - `src/baseline_tools.py`
  - `src/llm_client.py` (for “OpenAI Chat Completions wrapper” claim)
  - `docs/repo_structure_and_code_guide_v1.md`
- **Demo artifacts available**: `docs/example_interaction_picture_1.PNG`, `docs/example_interaction_picture_2.PNG`, `docs/example_interaction_picture_3.PNG`

### Assumptions avoided
- No claims about official hazard datasets (FHSZ), parcel boundary data, DEM slope computation, vegetation-ring distance analytics, or photo analysis being implemented (they are explicitly **not** in v1).
- No performance/accuracy claims (NDVI availability depends on Earth Engine setup; hazard/terrain/vegetation contexts are intentionally coarse).
- No claims about missing v1 docs being present; the deck does not cite files that aren’t in this repo snapshot.

### Discrepancies found (docs vs code)
- `PROJECT_STATE_AND_FLOW.md` appears partially **outdated** relative to current `src/agent.py` (tool-arg derivation, NDVI implementation, and `/api/plan` behavior). Details are in `presentation/recommendations.md`.
- README lists several `docs/*_v1.md` files that are not present in `docs/` here; the deck is built only from files that actually exist + code.

### Presentation readiness
- **Presentation-ready** as an editable deck source with professional diagrams.
- To make the demo slide more compelling, capture a few additional screenshots listed in `presentation/recommendations.md` (optional).

