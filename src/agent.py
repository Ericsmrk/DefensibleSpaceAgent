from __future__ import annotations

import json
from typing import Any, Dict

from .llm_client import LLMClient
from .prompts import GENERATOR_SYSTEM, PLANNER_SYSTEM, REPORTER_SYSTEM, VALIDATOR_SYSTEM
from .tools import classify_fuel, compute_mean_ndvi, geocode_google
from .validators import validate_coordinates, validate_plan, validate_tool_args


def _fallback_plan(user_request: str) -> Dict[str, Any]:
    return {
        "domain": "wildfire_defensible_space",
        "user_goal": user_request,
        "steps": [
            {"step_id": "S1", "objective": "Extract address", "tool": None, "constraints": ["JSON only"]},
            {"step_id": "S2", "objective": "Geocode address", "tool": "geocode_google", "constraints": ["No arbitrary tools"]},
            {"step_id": "S3", "objective": "Compute NDVI", "tool": "compute_mean_ndvi", "constraints": ["buffer <= 500m"]},
            {"step_id": "S4", "objective": "Classify fuel", "tool": "classify_fuel", "constraints": ["Use NDVI thresholds"]},
        ],
    }


def _fallback_tool_args(user_request: str) -> Dict[str, Any]:
    lowered = user_request.lower()
    address = "17825 Woodcrest Dr, Pioneer, Ca"
    for token in [" for ", " at "]:
        if token in lowered:
            idx = lowered.index(token) + len(token)
            candidate = user_request[idx:].strip(" .")
            if any(ch.isdigit() for ch in candidate):
                address = candidate
                break
    else:
        if any(ch.isdigit() for ch in user_request):
            address = user_request

    return {"address": address, "buffer_m": 100, "start": "2024-06-01", "end": "2024-09-01", "cloud_pct": 20}


def _fallback_validation() -> Dict[str, Any]:
    return {"passed": True, "reasons": ["fallback validator accepted request"]}


def run_agent(user_request: str, model: str = "gpt-4o-mini") -> Dict[str, Any]:
    client = LLMClient(model=model)

    plan = client.chat_json(
        PLANNER_SYSTEM,
        f"Create a plan for: {user_request}",
        fallback=_fallback_plan(user_request),
    )
    plan_ok, plan_reasons = validate_plan(plan)

    tool_args = client.chat_json(
        GENERATOR_SYSTEM,
        f"Given plan:\n{json.dumps(plan)}\nGenerate tool args for request: {user_request}",
        fallback=_fallback_tool_args(user_request),
    )
    args_ok, args_reasons = validate_tool_args(tool_args)

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
        buffer_m=tool_args["buffer_m"],
        start=tool_args["start"],
        end=tool_args["end"],
        cloud_pct=tool_args["cloud_pct"],
    )
    fuel_class = classify_fuel(ndvi)

    execution = {
        "address": tool_args["address"],
        "latitude": lat,
        "longitude": lon,
        "mean_ndvi": ndvi,
        "fuel_class": fuel_class,
        "confidence": "medium" if geocode_meta.get("source", "").startswith("mock") else "high",
        "evidence": {"geocode": geocode_meta, "ndvi": ndvi_meta},
    }

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
