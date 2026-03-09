from __future__ import annotations

from typing import Dict, List, Set, Tuple

# Internal execution spec (planner output): canonical keys, enums, and internal tool identifiers.
CANONICAL_PLAN_KEYS: Set[str] = {
    "request_type",
    "assessment_mode",
    "domain",
    "user_goal",
    "execution_ready",
    "missing_requirements",
    "location_strategy",
    "analysis_modules",
    "steps",
    "constraints",
    "recommended_next_action",
    "planner_summary",
}

VALID_REQUEST_TYPES: Set[str] = {"baseline_free_tier", "full_paid_tier", "incomplete", "unsupported"}
VALID_ASSESSMENT_MODES: Set[str] = {
    "address_level_baseline",
    "property_level_environmental_assessment",
    "incomplete_request",
    "unsupported_request",
}

LEGACY_REQUEST_TYPE_MAP: Dict[str, str] = {
    "address_baseline": "baseline_free_tier",
    "full_property_assessment": "full_paid_tier",
}

LEGACY_TOOL_MAP: Dict[str, str] = {
    "geocode_google": "resolve_location",
    "compute_mean_ndvi": "compute_property_ndvi",
    "classify_fuel": "classify_property_fuel",
}

ALLOWED_TOOLS: Set[str] = {
    "resolve_location",
    "validate_california_scope",
    "gather_hazard_context",
    "gather_terrain_context",
    "gather_regional_vegetation_context",
    "compute_property_ndvi",
    "classify_property_fuel",
    "analyze_property_slope",
    "analyze_vegetation_proximity",
    "analyze_uploaded_structure_photos",
    "generate_calfire_aligned_recommendations",
    "generate_baseline_report",
    "generate_full_report",
}

ALLOWED_ANALYSIS_MODULES: Set[str] = {
    "location_resolution",
    "california_scope_validation",
    "hazard_context_analysis",
    "terrain_context_analysis",
    "regional_vegetation_analysis",
    "baseline_report_synthesis",
    "property_vegetation_analysis",
    "fuel_classification",
    "property_slope_analysis",
    "vegetation_proximity_analysis",
    "structure_photo_analysis",
    "calfire_recommendation_generation",
    "full_report_synthesis",
}

ALLOWED_CONSTRAINT_KEYS: Set[str] = {"buffer_m", "cloud_pct", "photo_count", "date_window"}
REQUIRED_CONSTRAINT_KEYS: Set[str] = {"buffer_m", "cloud_pct"}


def _steps_use_tool(steps: list, tool_name: str) -> bool:
    """Return True if any step uses the given tool."""
    for s in steps or []:
        if isinstance(s, dict) and s.get("tool") == tool_name:
            return True
    return False


def normalize_plan(plan: Dict) -> Tuple[Dict, List[str]]:
    """
    Normalize known legacy planner outputs into the canonical planner schema.

    - Accepts legacy request_type/tool names and maps them to canonical values.
    - Fills missing canonical keys for legacy plans with conservative defaults.
    - Does NOT silently drop unknown keys (returns reasons instead).
    """
    reasons: List[str] = []
    if not isinstance(plan, dict):
        return {}, ["plan must be an object"]

    # If a plan has unknown top-level keys, flag it (do not drop).
    known_legacy_keys = {"steps", "location_strategy", "domain", "user_goal", "execution_ready", "request_type", "assessment_mode"}
    allowed_top_level = CANONICAL_PLAN_KEYS | known_legacy_keys
    extra = set(plan.keys()) - allowed_top_level
    if extra:
        reasons.append(f"plan contains unexpected top-level keys: {sorted(extra)}")

    out = dict(plan)

    # request_type legacy mapping
    rt = out.get("request_type")
    if isinstance(rt, str) and rt in LEGACY_REQUEST_TYPE_MAP:
        out["request_type"] = LEGACY_REQUEST_TYPE_MAP[rt]

    # tool legacy mapping
    steps = out.get("steps")
    if isinstance(steps, list):
        norm_steps = []
        for s in steps:
            if not isinstance(s, dict):
                norm_steps.append(s)
                continue
            tool = s.get("tool")
            if isinstance(tool, str) and tool in LEGACY_TOOL_MAP:
                s = dict(s)
                s["tool"] = LEGACY_TOOL_MAP[tool]
            norm_steps.append(s)
        out["steps"] = norm_steps

    # assessment_mode: normalize based on request_type when possible
    rt2 = out.get("request_type")
    if rt2 == "baseline_free_tier":
        out.setdefault("assessment_mode", "address_level_baseline")
    elif rt2 == "full_paid_tier":
        out.setdefault("assessment_mode", "property_level_environmental_assessment")
    elif rt2 == "incomplete":
        out.setdefault("assessment_mode", "incomplete_request")
    elif rt2 == "unsupported":
        out.setdefault("assessment_mode", "unsupported_request")

    # Fill missing canonical keys for legacy plans
    out.setdefault("domain", "wildfire_defensible_space")
    out.setdefault("missing_requirements", [])
    out.setdefault("location_strategy", out.get("location_strategy") if isinstance(out.get("location_strategy"), dict) else {"use_provided_coordinates": False, "needs_geocoding": False})
    out.setdefault("analysis_modules", [])
    out.setdefault("constraints", {"buffer_m": 120, "cloud_pct": 20})
    out.setdefault("recommended_next_action", "")
    out.setdefault("planner_summary", "")

    # If analysis_modules was populated with step tool identifiers, normalize to conceptual module names.
    if isinstance(out.get("analysis_modules"), list):
        tool_to_module = {
            "resolve_location": "location_resolution",
            "validate_california_scope": "california_scope_validation",
            "gather_hazard_context": "hazard_context_analysis",
            "gather_terrain_context": "terrain_context_analysis",
            "gather_regional_vegetation_context": "regional_vegetation_analysis",
            "compute_property_ndvi": "property_vegetation_analysis",
            "classify_property_fuel": "fuel_classification",
            "analyze_property_slope": "property_slope_analysis",
            "analyze_vegetation_proximity": "vegetation_proximity_analysis",
            "analyze_uploaded_structure_photos": "structure_photo_analysis",
            "generate_calfire_aligned_recommendations": "calfire_recommendation_generation",
            "generate_baseline_report": "baseline_report_synthesis",
            "generate_full_report": "full_report_synthesis",
        }
        mods_in = out.get("analysis_modules") or []
        mods_out: List[str] = []
        for m in mods_in:
            if not isinstance(m, str):
                reasons.append("analysis_modules must contain only strings")
                continue
            if m in ALLOWED_ANALYSIS_MODULES:
                mods_out.append(m)
            elif m in tool_to_module:
                mods_out.append(tool_to_module[m])
            else:
                # Keep as-is so validator can fail with a clear message.
                mods_out.append(m)
        out["analysis_modules"] = mods_out

    # Ensure required keys exist (strict); we don't add unknown keys beyond canonical.
    missing = CANONICAL_PLAN_KEYS - set(out.keys())
    if missing:
        reasons.append(f"missing plan keys: {sorted(missing)}")

    return out, reasons


def validate_plan(
    plan: Dict,
    *,
    provided_lat: float | None = None,
    provided_lng: float | None = None,
) -> Tuple[bool, List[str]]:
    """Validate the internal execution spec from the planner. Optionally validate against provided location context."""
    reasons: List[str] = []

    plan, norm_reasons = normalize_plan(plan)
    reasons.extend(norm_reasons)

    # Required top-level keys (strict + no extras)
    keys = set(plan.keys())
    missing = CANONICAL_PLAN_KEYS - keys
    if missing:
        reasons.append(f"missing plan keys: {sorted(missing)}")
    extra = keys - CANONICAL_PLAN_KEYS
    if extra:
        reasons.append(f"unexpected plan keys (must not include extras): {sorted(extra)}")

    # request_type must be valid
    rt = plan.get("request_type")
    if rt is not None and rt not in VALID_REQUEST_TYPES:
        reasons.append(f"invalid request_type: {rt!r}; must be one of {sorted(VALID_REQUEST_TYPES)}")

    # execution_ready consistency: incomplete/unsupported should not be execution_ready
    if plan.get("execution_ready") is True and rt in ("incomplete", "unsupported"):
        reasons.append("execution_ready must be false when request_type is incomplete or unsupported")

    # assessment_mode validity + consistency with request_type
    am = plan.get("assessment_mode")
    if am is not None and am not in VALID_ASSESSMENT_MODES:
        reasons.append(f"invalid assessment_mode: {am!r}; must be one of {sorted(VALID_ASSESSMENT_MODES)}")
    if rt == "baseline_free_tier" and am not in (None, "address_level_baseline"):
        reasons.append("assessment_mode must be address_level_baseline for baseline_free_tier")
    if rt == "full_paid_tier" and am not in (None, "property_level_environmental_assessment"):
        reasons.append("assessment_mode must be property_level_environmental_assessment for full_paid_tier")
    if rt == "incomplete" and am not in (None, "incomplete_request"):
        reasons.append("assessment_mode must be incomplete_request for incomplete")
    if rt == "unsupported" and am not in (None, "unsupported_request"):
        reasons.append("assessment_mode must be unsupported_request for unsupported")

    # domain must be exact
    if plan.get("domain") != "wildfire_defensible_space":
        reasons.append("domain must be 'wildfire_defensible_space'")

    # missing_requirements must be empty iff execution_ready is True
    missing_reqs = plan.get("missing_requirements")
    if not isinstance(missing_reqs, list):
        reasons.append("missing_requirements must be a list")
    else:
        if plan.get("execution_ready") is True and len(missing_reqs) != 0:
            reasons.append("missing_requirements must be empty when execution_ready is true")
        if plan.get("execution_ready") is False and len(missing_reqs) == 0:
            reasons.append("missing_requirements must be non-empty when execution_ready is false")

    # Location-strategy consistency with provided coordinates
    loc = plan.get("location_strategy") or {}
    if not isinstance(loc, dict):
        reasons.append("location_strategy must be an object")
        loc = {}
    use_provided = loc.get("use_provided_coordinates") is True
    needs_geocoding = loc.get("needs_geocoding") is True
    steps = plan.get("steps") or []
    has_resolve_step = _steps_use_tool(steps, "resolve_location")
    has_ndvi_step = _steps_use_tool(steps, "compute_property_ndvi")

    if use_provided and (provided_lat is None or provided_lng is None):
        reasons.append("plan sets use_provided_coordinates=true but no coordinates were supplied in context")
    if use_provided and has_resolve_step:
        reasons.append("plan sets use_provided_coordinates=true but includes resolve_location step (redundant)")
    if needs_geocoding and not has_resolve_step:
        # If geocoding is needed, resolve_location must be present and first.
        reasons.append("plan sets needs_geocoding=true but has no resolve_location step")
    if has_ndvi_step and not use_provided and not needs_geocoding:
        reasons.append("plan has compute_property_ndvi but location_strategy does not provide coordinates or geocoding")
    if needs_geocoding and steps and isinstance(steps[0], dict) and steps[0].get("tool") != "resolve_location":
        reasons.append("when needs_geocoding=true, the first step must be resolve_location")

    # steps: must be a list; non-empty when execution_ready is True
    steps = plan.get("steps")
    if not isinstance(steps, list):
        reasons.append("steps must be a list")
    elif not steps and plan.get("execution_ready") is True:
        reasons.append("steps must be non-empty when execution_ready is true")
    elif steps:
        step_ids: Set[int] = set()
        tool_order: List[str] = []
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                reasons.append(f"step {idx} must be an object")
                continue
            # Required step keys
            for k in ("step_id", "objective", "tool", "depends_on", "required"):
                if k not in step:
                    reasons.append(f"step {idx} missing key: {k}")
            tool = step.get("tool")
            if tool is not None:
                if tool not in ALLOWED_TOOLS:
                    reasons.append(f"step {idx} uses disallowed tool: {tool!r}")
                else:
                    tool_order.append(tool)
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
            else:
                reasons.append(f"step {idx} depends_on must be a list")

        # step_id should start at 1 and be contiguous (planner spec)
        if step_ids:
            expected = set(range(1, len(step_ids) + 1))
            if step_ids != expected:
                reasons.append("step_id values must start at 1 and be contiguous with no gaps")

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

        # Tier-specific tool constraints
        if rt == "baseline_free_tier":
            disallowed = {
                "compute_property_ndvi",
                "classify_property_fuel",
                "analyze_property_slope",
                "analyze_vegetation_proximity",
                "analyze_uploaded_structure_photos",
                "generate_calfire_aligned_recommendations",
                "generate_full_report",
            }
            if any(t in disallowed for t in tool_order):
                reasons.append("baseline_free_tier plan must not include property-level analysis or full-report tools")
            if "generate_baseline_report" not in tool_order:
                reasons.append("baseline_free_tier plan must include generate_baseline_report")
        if rt == "full_paid_tier":
            required_tools = {
                "validate_california_scope",
                "gather_hazard_context",
                "gather_terrain_context",
                "gather_regional_vegetation_context",
                "compute_property_ndvi",
                "classify_property_fuel",
                "analyze_property_slope",
                "analyze_vegetation_proximity",
                "generate_calfire_aligned_recommendations",
                "generate_full_report",
            }
            missing_tools = sorted(required_tools - set(tool_order))
            if missing_tools:
                reasons.append(f"full_paid_tier plan missing required tools: {missing_tools}")
            if tool_order and tool_order[-1] != "generate_full_report":
                reasons.append("full_paid_tier plan must end with generate_full_report")

        # Photo step consistency: only allowed when constraints.photo_count is present and > 0
        if "analyze_uploaded_structure_photos" in tool_order:
            c = plan.get("constraints") if isinstance(plan.get("constraints"), dict) else {}
            pc = c.get("photo_count") if isinstance(c, dict) else None
            if rt != "full_paid_tier":
                reasons.append("analyze_uploaded_structure_photos is only allowed for full_paid_tier")
            if pc is None or not isinstance(pc, (int, float)) or pc <= 0:
                reasons.append("analyze_uploaded_structure_photos requires constraints.photo_count > 0")

    # constraints: if present, buffer_m and cloud_pct should be in range
    constraints = plan.get("constraints")
    if isinstance(constraints, dict):
        extra_ck = set(constraints.keys()) - ALLOWED_CONSTRAINT_KEYS
        if extra_ck:
            reasons.append(f"constraints contains unexpected keys: {sorted(extra_ck)}")
        missing_ck = REQUIRED_CONSTRAINT_KEYS - set(constraints.keys())
        if missing_ck:
            reasons.append(f"constraints missing required keys: {sorted(missing_ck)}")
        buf = constraints.get("buffer_m")
        if buf is not None and (not isinstance(buf, (int, float)) or buf <= 0 or buf > 500):
            reasons.append("constraints.buffer_m must be in range 1..500")
        cp = constraints.get("cloud_pct")
        if cp is not None and (not isinstance(cp, (int, float)) or cp < 0 or cp > 100):
            reasons.append("constraints.cloud_pct must be in range 0..100")
        if "photo_count" in constraints and (not isinstance(constraints.get("photo_count"), (int, float)) or constraints.get("photo_count") < 0):
            reasons.append("constraints.photo_count must be a non-negative number when present")
        if "date_window" in constraints and not isinstance(constraints.get("date_window"), dict):
            reasons.append("constraints.date_window must be an object when present")
    else:
        reasons.append("constraints must be an object")

    # analysis_modules: enforce allowed conceptual names
    mods = plan.get("analysis_modules")
    if not isinstance(mods, list):
        reasons.append("analysis_modules must be a list")
    else:
        bad = [m for m in mods if not isinstance(m, str) or m not in ALLOWED_ANALYSIS_MODULES]
        if bad:
            reasons.append(f"analysis_modules contains invalid entries: {bad}")

    # recommended_next_action / planner_summary required
    if not isinstance(plan.get("recommended_next_action"), str) or not (plan.get("recommended_next_action") or "").strip():
        reasons.append("recommended_next_action must be a non-empty string")
    if not isinstance(plan.get("planner_summary"), str) or not (plan.get("planner_summary") or "").strip():
        reasons.append("planner_summary must be a non-empty string")

    return (len(reasons) == 0, reasons)


def validate_tool_args(args: Dict, *, plan: Dict | None = None) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if not isinstance(args, dict):
        return False, ["tool_args must be an object"]

    needs_address = False
    needs_ndvi_window = False
    if isinstance(plan, dict):
        steps = plan.get("steps") or []
        if _steps_use_tool(steps, "resolve_location"):
            needs_address = True
        if _steps_use_tool(steps, "compute_property_ndvi"):
            needs_ndvi_window = True

    buffer_m = args.get("buffer_m")
    cloud_pct = args.get("cloud_pct")

    if not isinstance(buffer_m, (int, float)) or buffer_m <= 0 or buffer_m > 500:
        reasons.append("buffer_m must be number in range 1..500")
    if not isinstance(cloud_pct, (int, float)) or cloud_pct < 0 or cloud_pct > 100:
        reasons.append("cloud_pct must be number in range 0..100")

    if needs_ndvi_window:
        if not isinstance(args.get("start"), str) or not args.get("start"):
            reasons.append("start must be a non-empty string when NDVI is required")
        if not isinstance(args.get("end"), str) or not args.get("end"):
            reasons.append("end must be a non-empty string when NDVI is required")

    if needs_address and not (args.get("address") or "").strip():
        reasons.append("address must be non-empty when resolve_location is required")

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
