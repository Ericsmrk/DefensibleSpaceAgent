### Recommended Code Changes – Version One (Documentation Only)

**File**: `docs/recommended_code_changes_v1.md`  
**Scope**: Implementation recommendations based on the current Version One codebase.  
**Rule**: These changes are **not** applied in Version One; they are suggestions for future refactors and enhancements.

---

### 1. Reading this document

Each recommendation is organized by:

- **Priority** – High / Medium / Low (relative impact and urgency)
- **Issue** – What is currently suboptimal
- **Rationale** – Why it matters
- **Expected benefit** – Concrete improvement if implemented
- **Risk if unchanged** – What might go wrong or stay confusing
- **Estimated difficulty** – Rough implementation effort (S / M / L)

This list is intentionally conservative and grounded in the **current repository**.

---

### 2. High‑priority recommendations

#### 2.1 Make California‑only scope explicit across UI and API

- **Priority**: High  
- **Issue**:  
  - The backend strictly enforces **California‑only** support (via `_in_ca_bounds` and `validate_california_scope`), but the UI copy and some examples still talk about “US addresses” generically.
- **Rationale**:  
  - Reviewers, users, and future maintainers should not be surprised by out‑of‑state rejections; the California‑only constraint is a central design choice.
- **Expected benefit**:  
  - Clearer user expectations and less confusion when non‑California addresses are rejected as unsupported.
  - Stronger alignment between SRS/SDD and implementation.
- **Risk if unchanged**:  
  - Confusing behavior for users entering out‑of‑state addresses.
  - Harder for reviewers to reconcile docs with behavior when tests enforce California‑only rules.
- **Estimated difficulty**: S  
- **Candidate changes (future)**:
  - Update text in `INDEX_HTML` (and `index.html`) to emphasize “California addresses only”.
  - Update any example requests in code/tests that implicitly suggest non‑California addresses (unless they are explicitly testing the unsupported path).

#### 2.2 Consolidate planner prompts and clarify “Planner” vs “Reporter” terminology

- **Priority**: High  
- **Issue**:  
  - There are two different “planner” concepts:
    - JSON execution‑spec planner in `src/prompts.py` used by `run_planner_only` and `run_agent`.
    - Text‑only planner prompt (`PLANNER_SYSTEM`/`PLANNER_PROMPT`) in `web_app.py` for the “Run planner” UI button.
  - Naming around “generator” vs “reporter” can be slightly confusing:
    - `GENERATOR_SYSTEM` is used as the final narrative writer for Full tier.
- **Rationale**:  
  - Clear naming and separation of responsibilities improves maintainability and reduces cognitive overhead when reading the code or prompts.
- **Expected benefit**:  
  - Easier to reason about which LLM is responsible for which stage.
  - Simpler future refactors (e.g., swapping out models or adding more stages).
- **Risk if unchanged**:  
  - Confusion during code review or when debugging prompts.
  - Higher risk of accidentally updating the wrong prompt when iterating.
- **Estimated difficulty**: M  
- **Candidate changes (future)**:
  - Rename the UI‑only text planner prompt in `web_app.py` to something like `UI_BASELINE_PREVIEW_SYSTEM` and `UI_BASELINE_PREVIEW_PROMPT`.
  - Add a short comment in `src/prompts.py` explaining that the **execution‑spec planner** is distinct from the **UI Baseline preview**.
  - Consider renaming `GENERATOR_SYSTEM` to `REPORTER_SYSTEM` or `FULL_REPORT_SYSTEM` for clarity, and updating usages accordingly.

#### 2.3 Factor `INDEX_HTML` out of `web_app.py` into a template/static file

- **Priority**: High  
- **Issue**:  
  - `web_app.py` embeds a very large `INDEX_HTML` string with HTML + CSS + JavaScript.
  - This makes diffs noisy and makes it difficult to quickly inspect the server logic vs. UI markup.
- **Rationale**:  
  - Separating concerns between server code and templates improves readability and aligns with common Flask practices.
- **Expected benefit**:  
  - Smaller, more focused `web_app.py`.
  - Easier to iterate on UI/UX without touching Python.
  - Cleaner diffs and code reviews.
- **Risk if unchanged**:  
  - UI and backend coupling remains high.
  - Future HTML/JS changes are more error‑prone and visually harder to review.
- **Estimated difficulty**: M  
- **Candidate changes (future)**:
  - Move `INDEX_HTML` into `templates/index.html` and load it with `render_template`.
  - Or, store the HTML in a separate `.html` file loaded at startup.

#### 2.4 Strengthen and centralize Earth Engine (NDVI) configuration and fallbacks

- **Priority**: High  
- **Issue**:  
  - `compute_mean_ndvi` depends on `earthengine-api` and requires credentials, but:
    - This dependency is not declared in `requirements.txt`.
    - NDVI unavailability is signaled via metadata, but behavior is not clearly surfaced in all UX paths.
- **Rationale**:  
  - NDVI is a major differentiator for the Full tier; its availability and behavior should be explicit and predictable.
- **Expected benefit**:  
  - Clearer understanding in tests and docs when NDVI is expected to be available vs. gracefully degraded.
  - Easier to adjust the NDVI window, cloud thresholds, and data source without hunting through code.
- **Risk if unchanged**:  
  - Confusion about why NDVI may be missing in different environments.
  - Difficulty reproducing results or debugging NDVI failures.
- **Estimated difficulty**: M  
- **Candidate changes (future)**:
  - Decide whether to:
    - add `earthengine-api` as an optional extra (e.g., in a `[ndvi]` extras section), or
    - document a separate installation step and conditions under which tests assume NDVI is available.
  - Consider surfacing a clearer NDVI availability flag in `execution` for the UI.

#### 2.5 Expand tests for Baseline executor and Baseline synthesis paths

- **Priority**: High  
- **Issue**:  
  - Tests currently exercise the planner, validators, and end‑to‑end agent behavior, but Baseline‑specific orchestration and synthesis (in `baseline_executor.py` and `baseline_tools.py`) appear less directly covered.
- **Rationale**:  
  - Baseline is a first‑class tier with its own executor and synthesis logic; it should have direct tests to guard against regressions.
- **Expected benefit**:  
  - Higher confidence when refactoring Baseline tools, adding new Baseline steps, or modifying prompts.
  - Clearer demonstration of structured Baseline behavior for reviewers.
- **Risk if unchanged**:  
  - Baseline behavior may be indirectly tested only through `run_agent`, making regressions harder to localize.
- **Estimated difficulty**: M  
- **Candidate changes (future)**:
  - Add tests that:
    - call `execute_baseline_workflow` directly on synthetic plans and contexts,
    - assert the shape of `BaselineOrchestratorResult` and `FinalBaselineReport`,
    - verify the fallback synthesis path when `OPENAI_API_KEY` is missing.

---

### 3. Medium‑priority recommendations

#### 3.1 Introduce structured configuration for tier behavior and thresholds

- **Priority**: Medium  
- **Issue**:  
  - Various constants are embedded in code (e.g., default `buffer_m`, NDVI date windows, Tier decisions in `_fallback_execution_spec`).
- **Rationale**:  
  - Centralized configuration would make it easier to experiment with different operational settings or adapt the system to new regions (if ever expanded) while still keeping California‑only rules explicit.
- **Expected benefit**:  
  - Less scattered “magic numbers”.
  - Improved traceability from SRS/SDD to concrete parameter values.
- **Risk if unchanged**:  
  - Adjusting thresholds requires searching through multiple functions.
- **Estimated difficulty**: M  

#### 3.2 Align Baseline vs Full flows behind a shared interface

- **Priority**: Medium  
- **Issue**:  
  - Baseline execution is implemented in a dedicated module (`baseline_executor.py`), while Full execution is hand‑coded inside `run_agent`.
- **Rationale**:  
  - A future‑proof design could treat each tier as a strategy implementing a common interface (e.g., `execute(plan, context, llm_client)`).
- **Expected benefit**:  
  - Cleaner separation of Baseline and Full logic.
  - Easier testing and extension (e.g., adding intermediate tiers or specialized flows).
- **Risk if unchanged**:  
  - `run_agent` continues to grow as more features are added.
- **Estimated difficulty**: M–L  

#### 3.3 Improve logging and observability for planner and executor stages

- **Priority**: Medium  
- **Issue**:  
  - Logging is present but relatively minimal; some key events and failures are only represented in returned JSON.
- **Rationale**:  
  - For operational deployments and debugging, structured logs at each major stage (planner, validators, Baseline executor, Full executor, NDVI calls) would be valuable.
- **Expected benefit**:  
  - Easier diagnosis of geocoding failures, NDVI errors, or planner misclassifications.
- **Risk if unchanged**:  
  - Reliance on client‑side inspection of JSON only.
- **Estimated difficulty**: M  

#### 3.4 Clarify test expectations under missing keys / external services

- **Priority**: Medium  
- **Issue**:  
  - Some tests implicitly assume that NDVI and other services are available, while others rely on fallback behavior.
- **Rationale**:  
  - Making the test suite explicit about which scenarios require external services vs. which run in offline/fallback mode would clarify expectations.
- **Expected benefit**:  
  - More portable test suite; easier to run reliably in CI and on new machines.
- **Risk if unchanged**:  
  - Intermittent or confusing test results across environments.
- **Estimated difficulty**: S–M  

---

### 4. Low‑priority recommendations

#### 4.1 Incrementally adopt static typing and type checking

- **Priority**: Low  
- **Issue**:  
  - Type hints exist in several locations but are not enforced with a type checker across the codebase.
- **Rationale**:  
  - Strong typing around planner outputs, tool args, and executor state would help catch shape mismatches early.
- **Expected benefit**:  
  - Safer refactors and clearer contracts.
- **Risk if unchanged**:  
  - Subtle shape changes might only be caught at runtime or in tests.
- **Estimated difficulty**: M–L (depending on breadth)  

#### 4.2 Introduce more granular modules for UI‑focused formatting

- **Priority**: Low  
- **Issue**:  
  - Several large JS/HTML snippets in `INDEX_HTML` combine data fetching, validation, and presentational formatting in one place.
- **Rationale**:  
  - Splitting formatting helpers from API logic would make front‑end behavior easier to reason about.
- **Expected benefit**:  
  - Cleaner frontend separation and easier UI testing.
- **Risk if unchanged**:  
  - Harder to extend the UI to new flows (e.g., photo upload) without adding complexity to the same file.
- **Estimated difficulty**: M  

---

### 5. Summary view (table)

| Priority | Issue (short label)                                           | Expected Benefit                                      | Risk if Unchanged                                   | Difficulty |
|---------|----------------------------------------------------------------|-------------------------------------------------------|-----------------------------------------------------|------------|
| High    | Clarify California‑only scope across UI/API                    | Consistent expectations, fewer surprises              | User confusion on out‑of‑state requests             | S          |
| High    | Consolidate planner/reporter terminology & prompts             | Clearer mental model of agent stages                  | Misunderstandings during maintenance and reviews    | M          |
| High    | Extract `INDEX_HTML` into template/static file                 | Cleaner server code, easier UI iteration              | Noisy diffs, coupling of UI and backend             | M          |
| High    | Strengthen Earth Engine/NDVI configuration & fallbacks         | Predictable NDVI behavior across environments         | Confusing NDVI availability and error modes         | M          |
| High    | Expand Baseline executor & synthesis tests                     | Stronger guarantees for Baseline tier                 | Undetected Baseline regressions                     | M          |
| Medium  | Centralize configuration for tier behavior and thresholds      | Easier experiments and clear parameter provenance     | Harder to tune or explain operational settings      | M          |
| Medium  | Align Baseline and Full flows behind shared interface          | Cleaner tier separation and future extensibility      | `run_agent` continues to grow in complexity         | M–L        |
| Medium  | Improve logging for planner/executor/NDVI                      | Easier debugging and operations                       | Harder to debug complex multi‑stage failures        | M          |
| Medium  | Clarify test expectations for missing keys/external services   | More portable and predictable test runs               | Environment‑specific test failures                  | S–M        |
| Low     | Incrementally adopt strict typing & checking                   | Safer refactors and clearer contracts                 | Shape mismatches only caught at runtime             | M–L        |
| Low     | Refine UI code structure for formatting vs. logic              | More maintainable frontend path                       | Harder UI extensions in later versions              | M          |

All of the above are **recommendations only** for post‑Version‑One evolution. Version One’s code remains unchanged; these items are documented to guide future work and to make explicit where the current implementation could be improved.

