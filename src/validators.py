from __future__ import annotations

from typing import Dict, List, Set, Tuple

# Internal execution spec: allowed tools and valid request types
ALLOWED_TOOLS: Set[str] = {"geocode_google", "compute_mean_ndvi", "classify_fuel"}
VALID_REQUEST_TYPES = {"address_baseline", "full_property_assessment", "incomplete", "unsupported"}
REQUIRED_PLAN_KEYS = {"request_type", "assessment_mode", "domain", "user_goal", "execution_ready", "steps"}
REQUIRED_TOOL_KEYS = {"address", "buffer_m", "start", "end", "cloud_pct"}


def _steps_use_tool(steps: list, tool_name: str) -> bool:
    """Return True if any step uses the given tool."""
    for s in steps or []:
        if isinstance(s, dict) and s.get("tool") == tool_name:
            return True
    return False


def validate_plan(
    plan: Dict,
    *,
    provided_lat: float | None = None,
    provided_lng: float | None = None,
) -> Tuple[bool, List[str]]:
    """Validate the internal execution spec from the planner. Optionally validate against provided location context."""
    reasons: List[str] = []

    # Required top-level keys
    missing = REQUIRED_PLAN_KEYS - set(plan.keys())
    if missing:
        reasons.append(f"missing plan keys: {sorted(missing)}")

    # request_type must be valid
    rt = plan.get("request_type")
    if rt is not None and rt not in VALID_REQUEST_TYPES:
        reasons.append(f"invalid request_type: {rt!r}; must be one of {sorted(VALID_REQUEST_TYPES)}")

    # execution_ready consistency: incomplete/unsupported should not be execution_ready
    if plan.get("execution_ready") is True and rt in ("incomplete", "unsupported"):
        reasons.append("execution_ready must be false when request_type is incomplete or unsupported")

    # Location-strategy consistency with provided coordinates
    loc = plan.get("location_strategy") or {}
    use_provided = loc.get("use_provided_coordinates") is True
    needs_geocoding = loc.get("needs_geocoding") is True
    steps = plan.get("steps") or []
    has_geocode_step = _steps_use_tool(steps, "geocode_google")
    has_ndvi_step = _steps_use_tool(steps, "compute_mean_ndvi")

    if use_provided and (provided_lat is None or provided_lng is None):
        reasons.append("plan sets use_provided_coordinates=true but no coordinates were supplied in context")
    if use_provided and has_geocode_step:
        reasons.append("plan sets use_provided_coordinates=true but includes geocode_google step (redundant)")
    if needs_geocoding and not has_geocode_step and has_ndvi_step:
        reasons.append("plan sets needs_geocoding=true and has coordinate-dependent steps but no geocode_google step")
    if has_ndvi_step and not use_provided and not needs_geocoding:
        reasons.append("plan has compute_mean_ndvi but location_strategy does not provide coordinates or geocoding")

    # steps: must be a list; non-empty when execution_ready is True
    steps = plan.get("steps")
    if not isinstance(steps, list):
        reasons.append("steps must be a list")
    elif not steps and plan.get("execution_ready") is True:
        reasons.append("steps must be non-empty when execution_ready is true")
    elif steps:
        step_ids: Set[int] = set()
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                reasons.append(f"step {idx} must be an object")
                continue
            tool = step.get("tool")
            if tool is not None and tool not in ALLOWED_TOOLS:
                reasons.append(f"step {idx} uses disallowed tool: {tool!r}")
            sid = step.get("step_id")
            if sid is not None:
                try:
                    sid_int = int(sid)
                    if sid_int in step_ids:
                        reasons.append(f"duplicate step_id: {sid_int}")
                    step_ids.add(sid_int)
                except (TypeError, ValueError):
                    reasons.append(f"step {idx} has invalid step_id: {sid!r}")
            depends_on = step.get("depends_on")
            if isinstance(depends_on, list):
                for dep in depends_on:
                    try:
                        int(dep)
                    except (TypeError, ValueError):
                        reasons.append(f"step {idx} depends_on contains non-integer: {dep!r}")

        # Dependency ordering: each step's depends_on must reference only earlier step_ids
        seen_so_far: Set[int] = set()
        for step in steps:
            if not isinstance(step, dict):
                continue
            sid = step.get("step_id")
            try:
                sid_int = int(sid) if sid is not None else None
            except (TypeError, ValueError):
                sid_int = None
            for dep in step.get("depends_on") or []:
                try:
                    d = int(dep)
                    if d not in seen_so_far:
                        reasons.append(f"step {sid_int} depends_on {d} but dependency must come before it in steps list")
                except (TypeError, ValueError):
                    pass
            if sid_int is not None:
                seen_so_far.add(sid_int)

    # constraints: if present, buffer_m and cloud_pct should be in range
    constraints = plan.get("constraints")
    if isinstance(constraints, dict):
        buf = constraints.get("buffer_m")
        if buf is not None and (not isinstance(buf, (int, float)) or buf <= 0 or buf > 500):
            reasons.append("constraints.buffer_m must be in range 1..500")
        cp = constraints.get("cloud_pct")
        if cp is not None and (not isinstance(cp, (int, float)) or cp < 0 or cp > 100):
            reasons.append("constraints.cloud_pct must be in range 0..100")

    return (len(reasons) == 0, reasons)


def validate_tool_args(args: Dict) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    missing = REQUIRED_TOOL_KEYS - set(args.keys())
    if missing:
        reasons.append(f"missing tool args keys: {sorted(missing)}")
        return False, reasons

    buffer_m = args.get("buffer_m")
    cloud_pct = args.get("cloud_pct")

    if not isinstance(buffer_m, (int, float)) or buffer_m <= 0 or buffer_m > 500:
        reasons.append("buffer_m must be number in range 1..500")
    if not isinstance(cloud_pct, (int, float)) or cloud_pct < 0 or cloud_pct > 100:
        reasons.append("cloud_pct must be number in range 0..100")

    if not args.get("address"):
        reasons.append("address must be non-empty")

    return (len(reasons) == 0, reasons)


def validate_coordinates(lat: float, lon: float) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if lat is None or lon is None:
        reasons.append("coordinates are missing")
        return False, reasons
    if not (-90 <= lat <= 90):
        reasons.append("latitude out of range")
    if not (-180 <= lon <= 180):
        reasons.append("longitude out of range")
    return (len(reasons) == 0, reasons)
