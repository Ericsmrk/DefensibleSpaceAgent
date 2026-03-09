from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from .llm_client import LLMClient

logger = logging.getLogger(__name__)
from .prompts import GENERATOR_SYSTEM, PLANNER_SYSTEM, REPORTER_SYSTEM, VALIDATOR_SYSTEM
from .tools import classify_fuel, compute_mean_ndvi, geocode_google
from .validators import validate_coordinates, validate_plan, validate_tool_args


def _planner_context(
    user_request: str,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    assessment_preference: Optional[str] = None,
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
    if assessment_preference in ("full_property_assessment", "address_baseline"):
        out["assessment_preference"] = assessment_preference
    return out


def _normalize_plan_for_provided_coordinates(plan: Dict[str, Any]) -> Dict[str, Any]:
    """When coordinates were provided, force plan to use them and remove geocode step."""
    plan = dict(plan)
    plan["location_strategy"] = {"use_provided_coordinates": True, "needs_geocoding": False}
    steps = list(plan.get("steps") or [])
    # Remove geocode_google steps and renumber; drop dependencies on removed steps
    steps = [dict(s) for s in steps if isinstance(s, dict) and s.get("tool") != "geocode_google"]
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
    # Drop "geocode" from analysis_modules when using provided coordinates
    modules = list(plan.get("analysis_modules") or [])
    if "geocode" in modules:
        plan["analysis_modules"] = [m for m in modules if m != "geocode"]
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
) -> Dict[str, Any]:
    """Fallback internal execution spec when LLM is unavailable or returns invalid JSON. Location-aware."""
    has_coords = lat is not None and lng is not None
    try:
        if has_coords:
            validate_coordinates(float(lat), float(lng))
    except (TypeError, ValueError):
        has_coords = False
    has_address = bool((address or "").strip())

    if has_coords:
        use_provided = True
        needs_geocoding = False
        steps = [
            {"step_id": 1, "objective": "Compute vegetation density around property", "tool": "compute_mean_ndvi", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Classify vegetation fuel load", "tool": "classify_fuel", "depends_on": [1], "required": True},
        ]
        execution_ready = True
        missing = []
        summary = "Plan ready using provided coordinates; no geocoding needed."
    elif has_address:
        use_provided = False
        needs_geocoding = True
        steps = [
            {"step_id": 1, "objective": "Resolve property location from address", "tool": "geocode_google", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Compute vegetation density around property", "tool": "compute_mean_ndvi", "depends_on": [1], "required": True},
            {"step_id": 3, "objective": "Classify vegetation fuel load", "tool": "classify_fuel", "depends_on": [2], "required": True},
        ]
        execution_ready = True
        missing = []
        summary = "Plan ready; geocoding will resolve address to coordinates."
    else:
        lowered = (user_request or "").strip().lower()
        has_implied_address = any(c.isdigit() for c in user_request or "") and (
            " for " in lowered or " at " in lowered or "address" in lowered or len((user_request or "").split()) >= 3
        )
        if has_implied_address:
            use_provided = False
            needs_geocoding = True
            steps = [
                {"step_id": 1, "objective": "Resolve property location from address", "tool": "geocode_google", "depends_on": [], "required": True},
                {"step_id": 2, "objective": "Compute vegetation density around property", "tool": "compute_mean_ndvi", "depends_on": [1], "required": True},
                {"step_id": 3, "objective": "Classify vegetation fuel load", "tool": "classify_fuel", "depends_on": [2], "required": True},
            ]
            execution_ready = True
            missing = []
            summary = "Plan ready for property-level assessment (address inferred from request)."
        else:
            use_provided = False
            needs_geocoding = False
            steps = []
            execution_ready = False
            missing = ["address or coordinates required"]
            summary = "Request is incomplete: provide an address or coordinates to run the assessment."

    return {
        "request_type": "full_property_assessment" if execution_ready else "incomplete",
        "assessment_mode": "property_level_environmental_assessment" if execution_ready else "address_level_baseline",
        "domain": "wildfire_defensible_space",
        "user_goal": (user_request or "").strip() or "Defensible space assessment",
        "execution_ready": execution_ready,
        "missing_requirements": missing,
        "location_strategy": {"use_provided_coordinates": use_provided, "needs_geocoding": needs_geocoding},
        "analysis_modules": ["geocode", "coordinate_validation", "ndvi", "fuel_classification"] if execution_ready and needs_geocoding else (["coordinate_validation", "ndvi", "fuel_classification"] if execution_ready else []),
        "steps": steps,
        "constraints": {"buffer_m": 120, "cloud_pct": 20, "date_window": {"start": "2024-06-01", "end": "2024-09-30"}},
        "recommended_next_action": "Run structured property-level environmental analysis" if execution_ready else "Provide an address or coordinates to continue.",
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
    fallback = _fallback_execution_spec(user_request, address=address, lat=lat, lng=lng)
    user_message = (prompt or "").strip() or json.dumps({"user_request": "Create a plan for a defensible-space assessment."})
    raw = client.chat_json(PLANNER_SYSTEM, user_message, fallback=fallback)
    if "request_type" not in raw:
        raw = fallback
    return raw


def run_agent(
    user_request: str,
    *,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    assessment_preference: Optional[str] = None,
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

    # 2. Generator: plan -> tool args (use provided address when available)
    tool_args = client.chat_json(
        GENERATOR_SYSTEM,
        f"Given plan:\n{json.dumps(plan)}\nGenerate tool args for request: {user_request}"
        + (f"\nUse this address when relevant: {address}" if address else ""),
        fallback=_fallback_tool_args(user_request, plan, address=address),
    )
    if address and not (tool_args.get("address") or "").strip():
        tool_args["address"] = address
    args_ok, args_reasons = validate_tool_args(tool_args)

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

    # 4. Executor: use provided lat/lng when available, else geocode
    if provided_lat is not None and provided_lng is not None:
        coord_ok, coord_reasons = validate_coordinates(provided_lat, provided_lng)
        if not coord_ok:
            return {
                "plan": plan,
                "tool_args": tool_args,
                "validation": {"passed": False, "reasons": coord_reasons},
                "execution": {},
                "final_response": "Provided coordinates are invalid.",
            }
        lat, lon, geocode_meta = provided_lat, provided_lng, {"source": "provided", "status": "OK"}
    else:
        lat, lon, geocode_meta = geocode_google(tool_args["address"])
        coord_ok, coord_reasons = validate_coordinates(lat, lon)
        if not coord_ok:
            return {
                "plan": plan,
                "tool_args": tool_args,
                "validation": {"passed": False, "reasons": coord_reasons},
                "execution": {"geocode": geocode_meta},
                "final_response": "Could not obtain valid coordinates.",
            }

    ndvi, ndvi_meta = compute_mean_ndvi(
        lat,
        lon,
        buffer_m=int(tool_args["buffer_m"]),
        start=tool_args["start"],
        end=tool_args["end"],
        cloud_pct=int(tool_args["cloud_pct"]),
    )
    fuel_class = classify_fuel(ndvi)

    execution = {
        "address": tool_args["address"],
        "latitude": lat,
        "longitude": lon,
        "mean_ndvi": ndvi,
        "fuel_class": fuel_class,
        "confidence": "high" if geocode_meta.get("source") == "provided" else ("medium" if (geocode_meta.get("source") or "").startswith("mock") else "high"),
        "evidence": {"geocode": geocode_meta, "ndvi": ndvi_meta},
    }

    # 5. Reporter
    fallback_text = (
        f"Assessment for {execution['address']}: NDVI={execution['mean_ndvi']}, "
        f"fuel class={execution['fuel_class']}. "
        "Prioritize clearing dead vegetation within 0-5 ft and reducing ladder fuels 5-30 ft."
    )
    final_response = client.chat_text(
        REPORTER_SYSTEM,
        f"Use this result JSON and produce concise actions:\n{json.dumps(execution)}",
        fallback=fallback_text,
    )

    return {
        "plan": plan,
        "tool_args": tool_args,
        "validation": {"passed": True, "reasons": []},
        "execution": execution,
        "final_response": final_response,
    }
