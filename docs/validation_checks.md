# Validation Checks

## Hard checks (rule-based)
- Allowed tools are whitelisted.
- Required JSON keys are present.
- `buffer_m` in 1..500.
- `cloud_pct` in 0..100.
- Coordinates in valid lat/lon ranges.

## Soft checks (LLM)
- Additional consistency approval stage before executing tools.
