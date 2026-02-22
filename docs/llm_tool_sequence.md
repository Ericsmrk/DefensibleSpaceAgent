# LLM + Tool Sequence

1. Planner call: produce constrained plan JSON.
2. Local validation of plan.
3. Generator call: produce tool args JSON.
4. Local validation of args.
5. Validator call: consistency/approval check.
6. Tool execution:
   - geocode_google
   - compute_mean_ndvi
   - classify_fuel
7. Reporter call: final recommendation narrative.
