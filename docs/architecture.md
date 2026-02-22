# Architecture Overview

## Modules
1. Planner (LLM) -> plan JSON
2. Generator (LLM) -> tool argument JSON
3. Validator (rule-based + LLM) -> pass/fail report
4. Executor (tools) -> geocode + NDVI + fuel class
5. Reporter (LLM) -> user-facing recommendations

## Core loop
`run_agent(user_request)` coordinates the full sequence and returns a single structured object with plan, args, validation, execution, and final response.
