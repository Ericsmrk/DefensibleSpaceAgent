from __future__ import annotations

import json
from typing import Any, Dict

from .llm_client import LLMClient
from .prompts import GENERATOR_SYSTEM, PLANNER_SYSTEM, REPORTER_SYSTEM, VALIDATOR_SYSTEM
from .tools import classify_fuel, compute_mean_ndvi, geocode_google
from .validators import validate_coordinates, validate_plan, validate_tool_args


def _fallback_execution_spec(user_request: str) -> Dict[str, Any]:
    """Fallback internal execution spec when LLM is unavailable or returns invalid JSON."""
    lowered = (user_request or "").strip().lower()
    has_address = any(c.isdigit() for c in user_request or "") and (
        " for " in lowered or " at " in lowered or "address" in lowered or len((user_request or "").split()) >= 3
    )
    request_type = "full_property_assessment" if has_address else "incomplete"
    execution_ready = has_address

    return {
        "request_type": request_type,
        "assessment_mode": "property_level_environmental_assessment" if has_address else "address_level_baseline",
        "domain": "wildfire_defensible_space",
        "user_goal": (user_request or "").strip() or "Defensible space assessment",
        "execution_ready": execution_ready,
        "missing_requirements": [] if has_address else ["address or coordinates required"],
        "location_strategy": {"use_provided_coordinates": False, "needs_geocoding": True},
        "analysis_modules": ["geocode", "coordinate_validation", "ndvi", "fuel_classification"] if has_address else [],
        "steps": [
            {"step_id": 1, "objective": "Resolve property location from address", "tool": "geocode_google", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Compute vegetation density around property", "tool": "compute_mean_ndvi", "depends_on": [1], "required": True},
            {"step_id": 3, "objective": "Classify vegetation fuel load", "tool": "classify_fuel", "depends_on": [2], "required": True},
        ] if has_address else [],
        "constraints": {"buffer_m": 120, "cloud_pct": 20, "date_window": {"start": "2024-06-01", "end": "2024-09-30"}},
        "recommended_next_action": "Run structured property-level environmental analysis" if has_address else "Provide an address or coordinates to continue.",
        "planner_summary": (
            f"Plan ready for property-level assessment (address inferred from request)."
            if has_address
            else "Request is incomplete: provide an address or coordinates to run the assessment."
        ),
    }


def _fallback_tool_args(user_request: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    lowered = (user_request or "").lower()
    address = "17825 Woodcrest Dr, Pioneer, Ca"
    for token in [" for ", " at "]:
        if token in lowered:
            idx = lowered.index(token) + len(token)
            candidate = (user_request or "")[idx:].strip(" .")
            if any(ch.isdigit() for ch in candidate):
                address = candidate
                break
    else:
        if any(ch.isdigit() for ch in (user_request or "")):
            address = (user_request or "").strip()
    constraints = plan.get("constraints") or {}
    return {
        "address": address,
        "buffer_m": constraints.get("buffer_m", 100),
        "start": (constraints.get("date_window") or {}).get("start", "2024-06-01"),
        "end": (constraints.get("date_window") or {}).get("end", "2024-09-01"),
        "cloud_pct": constraints.get("cloud_pct", 20),
    }


def _fallback_validation() -> Dict[str, Any]:
    return {"passed": True, "reasons": ["fallback validator accepted request"]}


def run_planner_only(prompt: str, model: str = "gpt-4o-mini") -> Dict[str, Any]:
    """Run only the internal planner; returns the structured execution spec (dict)."""
    client = LLMClient(model=model)
    user_message = (prompt or "").strip() or "Create a plan for a defensible-space assessment."
    raw = client.chat_json(
        PLANNER_SYSTEM,
        user_message,
        fallback=_fallback_execution_spec(prompt or ""),
    )
    # Normalize: ensure required keys exist so validation and downstream code are happy
    if "request_type" not in raw:
        raw = _fallback_execution_spec(prompt or "")
    return raw


def run_agent(
    user_request: str,
    model: str = "gpt-4o-mini",
    planner_prompt: str | None = None,
) -> Dict[str, Any]:
    """
    Pipeline: planner (execution spec) -> validate plan -> [if execution_ready] generator -> validate args
    -> validator LLM -> executor -> reporter.
    """
    client = LLMClient(model=model)
    planner_user = (planner_prompt or "").strip() or f"Create a plan for: {user_request}"

    # 1. Planner emits structured execution spec
    plan = run_planner_only(planner_user, model=model)
    plan_ok, plan_reasons = validate_plan(plan)

    # If plan invalid or not execution-ready, return early with plan and message
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

    # 2. Generator: plan -> tool args
    tool_args = client.chat_json(
        GENERATOR_SYSTEM,
        f"Given plan:\n{json.dumps(plan)}\nGenerate tool args for request: {user_request}",
        fallback=_fallback_tool_args(user_request, plan),
    )
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

    # 4. Executor: run tools
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
        "confidence": "medium" if (geocode_meta.get("source") or "").startswith("mock") else "high",
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
