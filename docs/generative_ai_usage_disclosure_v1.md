### Generative AI Usage Disclosure – Version One

**File**: `docs/generative_ai_usage_disclosure_v1.md`  
**Project**: ClearSafe California – Defensible Space Agent (Version One)  
**Author role**: Graduate‑level software engineering / agentic AI project

---

### 1. Purpose of this disclosure

This document transparently describes how **generative AI tools** were used in the development of **Version One (v1)** of the Defensible Space Agent / ClearSafe California codebase and documentation.

The goal is to provide:

- clarity for academic review,  
- transparency for future collaborators and stakeholders, and  
- a record of how AI‑assisted tooling supported, but did not replace, human engineering judgment.

---

### 2. Tools involved

The following generative AI–related tools and services were used in the lifecycle of this project:

- **OpenAI models** (via the OpenAI API)
  - Used inside the application itself (planner, validators, Baseline synthesis, CAL FIRE–aligned recommendations, reporter).
  - Used outside the application as a coding and design assistant (e.g., suggesting refactors, documentation structure, and prompt wording).
- **Cursor / Cursor Agent**
  - Used as an AI‑assisted IDE to:
    - navigate and understand the codebase,
    - propose code snippets and documentation drafts,
    - generate structured documentation (including this Version One documentation suite),
    - help maintain consistency across files.

Other standard tools (e.g., text editors, terminals, Git) were used in the usual way and are not considered generative AI tools.

---

### 3. How generative AI assisted the project

Generative AI tools were used as **assistants**, not as autonomous owners of design decisions or code quality. Their support fell roughly into four categories:

#### 3.1 Coding support

- Proposing initial implementations or refactors for:
  - orchestration logic (e.g., planner/executor structure),
  - validation rules and schemas,
  - test patterns and fixtures.
- Suggesting ways to structure Baseline and Full tier flows using common software engineering patterns.
- Helping identify edge cases or integration risks (e.g., missing keys, NDVI availability) that were then reviewed and adjusted by the project author.

All AI‑suggested code was **reviewed, edited, and integrated manually**. The current state of the repository is the authoritative record of what was accepted.

#### 3.2 Documentation support

- Drafting and iterating:
  - the Version One documentation set (SRS, SDD, architecture, UML/flowcharts, testing, setup, scope/limitations, future work),
  - the high‑level README and repo structure guide,
  - this generative AI usage disclosure.
- Helping ensure terminology and framing (Baseline vs Full, California‑only scope, CAL FIRE–aligned language) were consistent across documents.

Again, all documentation was **reviewed and curated** by the project author to ensure it matched the actual repository and did not invent capabilities.

#### 3.3 Ideation and exploration

- Brainstorming:
  - architectural options for structured agents,
  - possible validation strategies and tool sequences,
  - UX ideas for how homeowners might interact with the system,
  - potential future work directions (e.g., slope modeling, parcel‑level data, photo analysis).
- Evaluating trade‑offs between:
  - hard‑coded fallbacks vs. LLM‑only behavior,
  - strict vs. relaxed validation,
  - minimal vs. extended tier designs.

The final decisions documented in Version One reflect **human judgment**, taking these ideas as inputs, not as mandatory outputs.

#### 3.4 Iteration and refinement

- Using AI to:
  - suggest alternative phrasings for technical explanations,
  - check for structural gaps in documentation (e.g., missing sections in SRS/SDD),
  - propose diagram structures (Mermaid diagrams for architecture, UML, and flows).

Where AI suggestions conflicted with the actual implementation or project goals, the implementation and human review took precedence.

---

### 4. Boundaries and limitations of AI assistance

To maintain academic integrity and technical credibility, the following boundaries were maintained:

- **No blind acceptance**: AI‑generated code and documentation were **never blindly accepted**. Each change was reviewed and adapted by the project author.
- **Repository as source of truth**: In all cases, the **current repository** (code + tests) is the single source of truth for behavior. Documentation, including AI‑assisted drafts, was updated to reflect the repository—not the other way around.
- **No fabricated results**: AI was not used to fabricate performance claims, coverage metrics, or external evaluation results. Where functionality is partial, placeholder, or planned, it is labeled explicitly as such.
- **No automatic deployment control**: AI tools did not deploy code autonomously; deployment configuration (e.g., `render.yaml`, `Procfile`) and any hosting decisions remain under human control.

---

### 5. Responsible use considerations

The project treats generative AI as a **powerful but fallible tool**. Responsible use includes:

- **Interpretability and traceability**
  - Structured prompts and schemas (in `src/prompts.py` and `src/schemas.py`) help constrain LLM outputs.
  - Validation logic in `src/validators.py` and Baseline tooling explicitly checks and bounds what LLMs may produce.
- **Safety and scope**
  - CAL FIRE–aligned prompts explicitly forbid:
    - treating outputs as legal or code‑enforcement determinations,
    - inventing hazard labels or clearance measurements without evidence.
  - Baseline vs Full tiers clearly separate address‑level context from more detailed remote‑sensing evidence.
- **Transparency**
  - This disclosure and other Version One documentation explicitly state:
    - what is implemented vs. placeholder,
    - where uncertainty is high,
    - how AI and external tools are used in the pipeline.

These principles reflect a broader goal: demonstrating how **agentic AI and tool orchestration** can be used responsibly in socially important domains like wildfire mitigation, without overstating capabilities.

---

### 6. Accountability

Despite the use of OpenAI and Cursor / Cursor Agent:

- **Final accountability** for:
  - code structure and behavior,
  - correctness of tests,
  - faithfulness of documentation to the repository,
  - ethical framing and scope boundaries,

remains with the **human project author**.

Reviewers should:

- evaluate the system based on the **current Version One implementation and documentation**,  
- treat AI assistance purely as part of the development process—not as an assurance of correctness.

If inconsistencies between documentation and code are found, the expectation is that:

- the disagreement is treated as a documentation bug, not an AI guarantee, and  
- corrections are made manually by the author in a future version.

