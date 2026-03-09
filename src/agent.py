from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from .llm_client import LLMClient

logger = logging.getLogger(__name__)
from .prompts import EXECUTION_SYSTEM, GENERATOR_SYSTEM, PLANNER_PROMPT, PLANNER_SYSTEM, VALIDATOR_SYSTEM
from .tools import classify_fuel, compute_mean_ndvi, geocode_google
from .validators import normalize_plan, validate_coordinates, validate_plan, validate_tool_args


def _planner_context(
    user_request: str,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    assessment_preference: Optional[str] = None,
    uploaded_photos_present: Optional[bool] = None,
    uploaded_photos_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Build structured context for the planner. Used as the planner user payload (instruction-only system; context in user message)."""
    out = {
        "user_request": (user_request or "").strip(),
        "provided_address": address.strip() if address else None,
        "provided_coordinates": None,
        "source": "request_only",
    }
    if lat is not None and lng is not None:
        try:
            out["provided_coordinates"] = {"lat": float(lat), "lng": float(lng)}
            if address:
                out["source"] = "google_places_selection"
            else:
                out["source"] = "provided_coordinates"
        except (TypeError, ValueError):
            out["provided_coordinates"] = None
    elif address:
        out["source"] = "address_only"
    if assessment_preference in ("full_paid_tier", "baseline_free_tier"):
        out["assessment_preference"] = assessment_preference
    if uploaded_photos_present is True:
        out["uploaded_photos_present"] = True
        if uploaded_photos_count is not None:
            try:
                out["uploaded_photos_count"] = int(uploaded_photos_count)
            except (TypeError, ValueError):
                pass
    return out


def _normalize_plan_for_provided_coordinates(plan: Dict[str, Any]) -> Dict[str, Any]:
    """When coordinates were provided, force plan to use them and remove geocode step."""
    plan = dict(plan)
    plan["location_strategy"] = {"use_provided_coordinates": True, "needs_geocoding": False}
    steps = list(plan.get("steps") or [])
    # Remove resolve_location steps and renumber; drop dependencies on removed steps
    steps = [dict(s) for s in steps if isinstance(s, dict) and s.get("tool") != "resolve_location"]
    old_to_new: Dict[int, int] = {}
    for i, s in enumerate(steps, start=1):
        old_id = s.get("step_id")
        if old_id is not None:
            old_to_new[int(old_id)] = i
        s["step_id"] = i
    for s in steps:
        dep = s.get("depends_on")
        if isinstance(dep, list):
            # Only keep dependencies that still exist (point to non-removed steps)
            s["depends_on"] = [old_to_new[int(d)] for d in dep if d is not None and int(d) in old_to_new]
    plan["steps"] = steps
    # Drop "location_resolution" from analysis_modules when using provided coordinates
    modules = list(plan.get("analysis_modules") or [])
    if "location_resolution" in modules:
        plan["analysis_modules"] = [m for m in modules if m != "location_resolution"]
    summary = plan.get("planner_summary") or ""
    if "geocod" in summary.lower():
        plan["planner_summary"] = "Plan ready using provided coordinates; no geocoding needed."
    return plan


def normalize_plan_for_provided_coordinates(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Public entry point for normalizing a plan when coordinates were provided (e.g. from /api/plan)."""
    return _normalize_plan_for_provided_coordinates(plan)


def _parse_planner_context(prompt: str) -> Dict[str, Any]:
    """Parse planner user message (JSON context) to extract user_request and optional location."""
    try:
        data = json.loads(prompt)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {"user_request": (prompt or "").strip(), "provided_address": None, "provided_coordinates": None, "source": "request_only"}


def _fallback_execution_spec(
    user_request: str,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    assessment_preference: Optional[str] = None,
    uploaded_photos_present: Optional[bool] = None,
    uploaded_photos_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Fallback internal execution spec when LLM is unavailable or returns invalid JSON. Location-aware."""
    has_coords = lat is not None and lng is not None
    try:
        if has_coords:
            validate_coordinates(float(lat), float(lng))
    except (TypeError, ValueError):
        has_coords = False
    has_address = bool((address or "").strip())
    lowered = (user_request or "").strip().lower()

    # Heuristics for fallback classification (used only when planner LLM is unavailable).
    property_intent = any(
        k in lowered
        for k in (
            "assess",
            "assessment",
            "my property",
            "my home",
            "my house",
            "defensible space",
            "wildfire risk",
            "fire risk",
        )
    )
    general_question = (
        (
            lowered.startswith(("what ", "why ", "how ", "tell me", "explain"))
            or any(k in lowered for k in ("what is", "tell me about", "how do", "why do"))
            or lowered.endswith("?")
        )
        and not property_intent
    )

    def _looks_out_of_ca(text: str) -> bool:
        t = (text or "").lower()
        if not t:
            return False
        if "california" in t or ", ca" in t or " ca " in t:
            return False
        # very small heuristic list; planner LLM should handle most cases when configured
        return any(x in t for x in (", tx", ", ny", ", fl", ", wa", "texas", "new york", "florida", "washington state"))

    if _looks_out_of_ca(address or "") or _looks_out_of_ca(user_request or ""):
        request_type = "unsupported"
        assessment_mode = "unsupported_request"
        execution_ready = False
        missing = ["California-only system: location appears outside California"]
        location_strategy = {"use_provided_coordinates": False, "needs_geocoding": False}
        analysis_modules = []
        steps = []
        recommended = "This system only supports California property assessments."
        summary = "Unsupported request: this system only supports California property-level or address-level wildfire assessments."
    elif general_question and not (has_address or has_coords):
        request_type = "unsupported"
        assessment_mode = "unsupported_request"
        execution_ready = False
        missing = ["Request is not a California property assessment"]
        location_strategy = {"use_provided_coordinates": False, "needs_geocoding": False}
        analysis_modules = []
        steps = []
        recommended = "Request a California property address or coordinates to continue."
        summary = "Unsupported request: this system is designed for California property wildfire/defensible-space assessments."
    else:
        pref = assessment_preference if assessment_preference in ("baseline_free_tier", "full_paid_tier") else None
        # Default to baseline when preference is absent (safer), but keep property intent as a hint.
        desired = pref or ("full_paid_tier" if property_intent else "baseline_free_tier")

        if not (has_address or has_coords):
            request_type = "incomplete"
            assessment_mode = "incomplete_request"
            execution_ready = False
            missing = ["California property address or coordinates required"]
            location_strategy = {"use_provided_coordinates": False, "needs_geocoding": False}
            analysis_modules = []
            steps = []
            recommended = "Request a California property address or coordinates to continue."
            summary = "Request is incomplete: provide a California property address or coordinates to run an assessment."
        else:
            request_type = desired
            assessment_mode = "address_level_baseline" if request_type == "baseline_free_tier" else "property_level_environmental_assessment"
            execution_ready = True
            missing = []
            use_provided = bool(has_coords)
            needs_geocoding = bool(has_address and not has_coords)
            location_strategy = {"use_provided_coordinates": use_provided, "needs_geocoding": needs_geocoding}

            steps_list = []
            step_id = 1
            if needs_geocoding:
                steps_list.append(
                    {"step_id": step_id, "objective": "Resolve property location from address", "tool": "resolve_location", "depends_on": [], "required": True}
                )
                step_id += 1

            def _add(obj: str, tool: str, deps: list[int]):
                nonlocal step_id
                steps_list.append({"step_id": step_id, "objective": obj, "tool": tool, "depends_on": deps, "required": True})
                step_id += 1

            # Baseline context
            deps0 = [steps_list[-1]["step_id"]] if steps_list else []
            _add("Validate California-only scope", "validate_california_scope", deps0)
            _add("Gather California wildfire hazard context", "gather_hazard_context", [steps_list[-1]["step_id"]])
            _add("Gather terrain context (regional)", "gather_terrain_context", [steps_list[-1]["step_id"]])
            _add("Gather regional vegetation / land-cover context", "gather_regional_vegetation_context", [steps_list[-1]["step_id"]])

            if request_type == "baseline_free_tier":
                _add("Generate baseline (address-level) report", "generate_baseline_report", [steps_list[-1]["step_id"]])
                analysis_modules = [
                    ("location_resolution" if needs_geocoding else None),
                    "california_scope_validation",
                    "hazard_context_analysis",
                    "terrain_context_analysis",
                    "regional_vegetation_analysis",
                    "baseline_report_synthesis",
                ]
                analysis_modules = [m for m in analysis_modules if m]
                recommended = "Resolve the property location and gather California baseline context." if needs_geocoding else "Gather California baseline context for the selected location."
                summary = "Baseline (Free Tier) plan for a California address-level wildfire overview using hazard, terrain, and regional vegetation context."
            else:
                _add("Compute property-centered vegetation index (NDVI)", "compute_property_ndvi", [steps_list[-1]["step_id"]])
                _add("Classify property fuel conditions", "classify_property_fuel", [steps_list[-1]["step_id"]])
                _add("Analyze property slope (terrain interpretation)", "analyze_property_slope", [steps_list[-1]["step_id"]])
                _add("Analyze vegetation proximity / ring context", "analyze_vegetation_proximity", [steps_list[-1]["step_id"]])
                if uploaded_photos_present is True:
                    _add("Analyze uploaded structure/property photos", "analyze_uploaded_structure_photos", [steps_list[-1]["step_id"]])
                _add("Generate CAL FIRE–aligned defensible-space recommendations", "generate_calfire_aligned_recommendations", [steps_list[-1]["step_id"]])
                _add("Generate full (paid tier) report", "generate_full_report", [steps_list[-1]["step_id"]])
                analysis_modules = [
                    ("location_resolution" if needs_geocoding else None),
                    "california_scope_validation",
                    "hazard_context_analysis",
                    "terrain_context_analysis",
                    "regional_vegetation_analysis",
                    "property_vegetation_analysis",
                    "fuel_classification",
                    "property_slope_analysis",
                    "vegetation_proximity_analysis",
                    ("structure_photo_analysis" if uploaded_photos_present is True else None),
                    "calfire_recommendation_generation",
                    "full_report_synthesis",
                ]
                analysis_modules = [m for m in analysis_modules if m]
                recommended = "Run the full property analysis pipeline for the selected California location."
                summary = "Full (Paid Tier) plan for a California property-focused wildfire assessment with property vegetation, fuel, slope, and proximity analysis."

            steps = steps_list
            constraints = {"buffer_m": 120, "cloud_pct": 20}
            if uploaded_photos_present is True:
                constraints["photo_count"] = int(uploaded_photos_count or 0) if str(uploaded_photos_count or "").strip() else 0
            return {
                "request_type": request_type,
                "assessment_mode": assessment_mode,
                "domain": "wildfire_defensible_space",
                "user_goal": (user_request or "").strip() or "Wildfire defensible-space assessment",
                "execution_ready": execution_ready,
                "missing_requirements": missing,
                "location_strategy": location_strategy,
                "analysis_modules": analysis_modules,
                "steps": steps,
                "constraints": constraints,
                "recommended_next_action": recommended,
                "planner_summary": summary,
            }

    return {
        "request_type": request_type,
        "assessment_mode": assessment_mode,
        "domain": "wildfire_defensible_space",
        "user_goal": (user_request or "").strip() or "Wildfire defensible-space assessment",
        "execution_ready": execution_ready,
        "missing_requirements": missing,
        "location_strategy": location_strategy,
        "analysis_modules": analysis_modules,
        "steps": steps,
        "constraints": {"buffer_m": 120, "cloud_pct": 20},
        "recommended_next_action": recommended,
        "planner_summary": summary,
    }


def _fallback_tool_args(
    user_request: str,
    plan: Dict[str, Any],
    address: Optional[str] = None,
) -> Dict[str, Any]:
    constraints = plan.get("constraints") or {}
    addr = (address or "").strip()
    if not addr:
        lowered = (user_request or "").lower()
        for token in [" for ", " at "]:
            if token in lowered:
                idx = lowered.index(token) + len(token)
                candidate = (user_request or "")[idx:].strip(" .")
                if any(ch.isdigit() for ch in candidate):
                    addr = candidate
                    break
        if not addr and any(ch.isdigit() for ch in (user_request or "")):
            addr = (user_request or "").strip()
        if not addr:
            addr = "17825 Woodcrest Dr, Pioneer, Ca"
    return {
        "address": addr,
        "buffer_m": constraints.get("buffer_m", 100),
        "start": (constraints.get("date_window") or {}).get("start", "2024-06-01"),
        "end": (constraints.get("date_window") or {}).get("end", "2024-09-01"),
        "cloud_pct": constraints.get("cloud_pct", 20),
    }


def _fallback_validation() -> Dict[str, Any]:
    return {"passed": True, "reasons": ["fallback validator accepted request"]}


def run_planner_only(prompt: str, model: str = "gpt-4o-mini") -> Dict[str, Any]:
    """Run only the internal planner. Prompt should be JSON context (user_request, provided_address, provided_coordinates, source)."""
    client = LLMClient(model=model)
    context = _parse_planner_context(prompt)
    user_request = context.get("user_request") or (prompt or "").strip()
    coords = context.get("provided_coordinates")
    lat = lng = None
    if isinstance(coords, dict):
        lat, lng = coords.get("lat"), coords.get("lng")
        if lat is not None and lng is not None:
            try:
                lat, lng = float(lat), float(lng)
            except (TypeError, ValueError):
                lat, lng = None, None
    address = (context.get("provided_address") or "").strip() or None
    fallback = _fallback_execution_spec(
        user_request,
        address=address,
        lat=lat,
        lng=lng,
        assessment_preference=context.get("assessment_preference"),
        uploaded_photos_present=context.get("uploaded_photos_present"),
        uploaded_photos_count=context.get("uploaded_photos_count"),
    )
    user_message = (prompt or "").strip() or json.dumps({"user_request": "Create a plan for a defensible-space assessment."})
    raw = client.chat_json(PLANNER_SYSTEM, f"{PLANNER_PROMPT}\n\n{user_message}", fallback=fallback)
    if "request_type" not in raw:
        raw = fallback
    normalized, norm_reasons = normalize_plan(raw)
    if norm_reasons:
        return fallback
    return normalized


def run_agent(
    user_request: str,
    *,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    assessment_preference: Optional[str] = None,
    uploaded_photos_present: Optional[bool] = None,
    uploaded_photos_count: Optional[int] = None,
    model: str = "gpt-4o-mini",
    planner_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pipeline: planner (execution spec) -> validate plan -> [if execution_ready] generator -> validate args
    -> validator LLM -> executor -> reporter.
    When address/lat/lng are provided (e.g. from Google Places UI), planner and executor use them;
    geocoding is skipped when valid coordinates are provided.
    """
    client = LLMClient(model=model)
    # Normalize lat/lng
    provided_lat, provided_lng = None, None
    if lat is not None and lng is not None:
        try:
            provided_lat, provided_lng = float(lat), float(lng)
        except (TypeError, ValueError):
            pass
    context = _planner_context(
        user_request,
        address=address,
        lat=provided_lat,
        lng=provided_lng,
        assessment_preference=assessment_preference,
        uploaded_photos_present=uploaded_photos_present,
        uploaded_photos_count=uploaded_photos_count,
    )
    planner_user = json.dumps(context) if not (planner_prompt or "").strip() else planner_prompt.strip()

    # Debug: log planner payload so we can verify provided_coordinates when lat/lng are available
    logger.info(
        "planner payload: %s",
        json.dumps({k: v for k, v in context.items()}, default=str),
    )

    # 1. Planner emits structured execution spec (location-aware)
    plan = run_planner_only(planner_user, model=model)

    # When we have provided coordinates, normalize plan so location_strategy and steps are consistent
    # (LLM may still output use_provided_coordinates=false; we override to match reality)
    if provided_lat is not None and provided_lng is not None:
        plan = _normalize_plan_for_provided_coordinates(plan)

    # Ensure canonical schema (accept known legacy outputs, but do not drop unknowns)
    plan, _ = normalize_plan(plan)

    logger.info(
        "planner output location_strategy: %s",
        plan.get("location_strategy"),
    )

    plan_ok, plan_reasons = validate_plan(plan, provided_lat=provided_lat, provided_lng=provided_lng)

    execution_ready = plan.get("execution_ready") is True
    if not plan_ok or not execution_ready:
        reasons = plan_reasons
        if not execution_ready and plan_ok:
            reasons = reasons + ["Plan not execution-ready (missing requirements or unsupported request)."]
        return {
            "plan": plan,
            "tool_args": {},
            "validation": {"passed": False, "reasons": reasons},
            "execution": {},
            "final_response": plan.get("planner_summary") or "Request cannot be executed. Provide an address or check request type.",
        }

    def _tool_args_from_plan(plan_obj: Dict[str, Any]) -> Dict[str, Any]:
        constraints = plan_obj.get("constraints") or {}
        buf = constraints.get("buffer_m", 120)
        cp = constraints.get("cloud_pct", 20)
        dw = constraints.get("date_window") if isinstance(constraints.get("date_window"), dict) else {}
        start = dw.get("start") or "2024-06-01"
        end = dw.get("end") or "2024-09-01"
        return {
            "address": (address or "").strip(),
            "buffer_m": int(buf) if isinstance(buf, (int, float)) else 120,
            "start": str(start),
            "end": str(end),
            "cloud_pct": int(cp) if isinstance(cp, (int, float)) else 20,
        }

    # 2. Tool args (derived deterministically from constraints and context)
    tool_args = _tool_args_from_plan(plan)
    if not (tool_args.get("address") or "").strip() and address:
        tool_args["address"] = address
    if not (tool_args.get("address") or "").strip():
        if any(isinstance(s, dict) and s.get("tool") == "resolve_location" for s in (plan.get("steps") or [])):
            tool_args = _fallback_tool_args(user_request, plan, address=address)
    args_ok, args_reasons = validate_tool_args(tool_args, plan=plan)

    # 3. Validator LLM
    validator_llm = client.chat_json(
        VALIDATOR_SYSTEM,
        f"Plan valid={plan_ok}, reasons={plan_reasons}; args valid={args_ok}, reasons={args_reasons}",
        fallback=_fallback_validation(),
    )

    if not (plan_ok and args_ok and validator_llm.get("passed", False)):
        return {
            "plan": plan,
            "tool_args": tool_args,
            "validation": {
                "passed": False,
                "reasons": plan_reasons + args_reasons + validator_llm.get("reasons", []),
            },
            "execution": {},
            "final_response": "Request blocked by validation checks.",
        }

    # 4. Executor: run the plan steps using internal tool identifiers
    def _in_ca_bounds(lat_v: float, lon_v: float) -> bool:
        # Approximate bounding box for California; used as a safety backstop only.
        return 32.0 <= float(lat_v) <= 42.5 and -124.7 <= float(lon_v) <= -114.0

    # Initialize state with provided coordinates if available
    execution: Dict[str, Any] = {
        "tier": plan.get("request_type"),
        "address": (tool_args.get("address") or "").strip() or address,
        "latitude": provided_lat,
        "longitude": provided_lng,
        "evidence": {"geocode": {"source": "provided", "status": "OK"}} if (provided_lat is not None and provided_lng is not None) else {"geocode": {}},
        "hazard_context": None,
        "terrain_context": None,
        "regional_vegetation_context": None,
        "mean_ndvi": None,
        "fuel_class": None,
        "property_slope": None,
        "vegetation_proximity": None,
        "photo_analysis": None,
        "calfire_recommendations": None,
        "report": None,
    }

    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        if tool is None:
            continue

        if tool == "resolve_location":
            lat2, lon2, meta = geocode_google(tool_args.get("address") or "")
            coord_ok, coord_reasons = validate_coordinates(lat2, lon2)
            if not coord_ok:
                return {
                    "plan": plan,
                    "tool_args": tool_args,
                    "validation": {"passed": False, "reasons": coord_reasons},
                    "execution": {"geocode": meta},
                    "final_response": "Could not obtain valid coordinates.",
                }
            execution["latitude"], execution["longitude"] = lat2, lon2
            execution["evidence"]["geocode"] = meta

        elif tool == "validate_california_scope":
            lat2, lon2 = execution.get("latitude"), execution.get("longitude")
            if lat2 is None or lon2 is None:
                return {
                    "plan": plan,
                    "tool_args": tool_args,
                    "validation": {"passed": False, "reasons": ["Location is not resolved; cannot validate California scope."]},
                    "execution": execution,
                    "final_response": "Could not validate California scope without a resolved location.",
                }
            if not _in_ca_bounds(float(lat2), float(lon2)):
                return {
                    "plan": plan,
                    "tool_args": tool_args,
                    "validation": {"passed": False, "reasons": ["Location appears outside California (safety check)."]},
                    "execution": execution,
                    "final_response": "Unsupported request: this system only supports California locations.",
                }

        elif tool == "gather_hazard_context":
            execution["hazard_context"] = {
                "summary": "California wildfire hazard context gathered at a regional level (no parcel-specific hazard layers in this build)."
            }

        elif tool == "gather_terrain_context":
            execution["terrain_context"] = {
                "summary": "Terrain context gathered at a regional level; property-level slope interpretation is included only in the full tier."
            }

        elif tool == "gather_regional_vegetation_context":
            execution["regional_vegetation_context"] = {
                "summary": "Regional vegetation/land-cover context gathered (coarse, non-parcel-specific in this build)."
            }

        elif tool == "compute_property_ndvi":
            lat2, lon2 = execution.get("latitude"), execution.get("longitude")
            if lat2 is None or lon2 is None:
                return {
                    "plan": plan,
                    "tool_args": tool_args,
                    "validation": {"passed": False, "reasons": ["Location is not resolved; cannot compute NDVI."]},
                    "execution": execution,
                    "final_response": "Could not compute property NDVI without a resolved location.",
                }
            ndvi, ndvi_meta = compute_mean_ndvi(
                float(lat2),
                float(lon2),
                buffer_m=int(tool_args["buffer_m"]),
                start=tool_args["start"],
                end=tool_args["end"],
                cloud_pct=int(tool_args["cloud_pct"]),
            )
            execution["mean_ndvi"] = ndvi
            execution["evidence"]["ndvi"] = ndvi_meta

        elif tool == "classify_property_fuel":
            execution["fuel_class"] = classify_fuel(execution.get("mean_ndvi"))

        elif tool == "analyze_property_slope":
            execution["property_slope"] = {"summary": "Not available in this build (no terrain model configured)."}

        elif tool == "analyze_vegetation_proximity":
            execution["vegetation_proximity"] = {"summary": "Not available in this build (no vegetation proximity model configured)."}

        elif tool == "analyze_uploaded_structure_photos":
            photo_count = (plan.get("constraints") or {}).get("photo_count")
            execution["photo_analysis"] = {"summary": "Photo analysis placeholder (image analysis not wired in this build).", "photo_count": photo_count}

        elif tool == "generate_calfire_aligned_recommendations":
            execution["calfire_recommendations"] = [
                "Maintain an ember-resistant zone within 0–5 feet of structures (reduce combustibles adjacent to buildings).",
                "Reduce and separate vegetation in the 5–30 foot zone to limit ladder fuels and flame contact.",
                "Manage vegetation and surface fuels in the 30–100 foot zone to reduce spread potential and ember generation.",
            ]

        elif tool == "generate_baseline_report":
            execution["report"] = {
                "tier": "baseline_free_tier",
                "summary": "Baseline report synthesized from California hazard, terrain, and regional vegetation context (no parcel-specific environmental analysis).",
            }

        elif tool == "generate_full_report":
            execution["report"] = {
                "tier": "full_paid_tier",
                "summary": "Full report synthesized from baseline context plus property-centered vegetation/fuel/slope/proximity analysis (as available).",
            }

    # 5. Reporter
    fallback_text = (
        "Baseline (Free Tier) California wildfire overview is ready."
        if plan.get("request_type") == "baseline_free_tier"
        else "Full (Paid Tier) California wildfire assessment is ready."
    )
    final_response = client.chat_text(
        GENERATOR_SYSTEM,
        f"Plan:\n{json.dumps(plan)}\n\nExecution evidence:\n{json.dumps(execution)}",
        fallback=fallback_text,
    )

    return {
        "plan": plan,
        "tool_args": tool_args,
        "validation": {"passed": True, "reasons": []},
        "execution": execution,
        "final_response": final_response,
    }
