from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from .baseline_executor import execute_baseline_workflow
from .llm_client import LLMClient

logger = logging.getLogger(__name__)
from .prompts import (
    CALFIRE_RECOMMENDATION_SYSTEM,
    EXECUTION_SYSTEM,
    GENERATOR_SYSTEM,
    PLANNER_PROMPT,
    PLANNER_SYSTEM,
    VALIDATOR_SYSTEM,
)
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


def _strip_markdown_like(text: str) -> str:
    """Remove common markdown artifacts (e.g., headings, bullets, code fences) from LLM text."""
    if not isinstance(text, str):
        return ""
    s = text.strip()
    # Remove leading code fences and headings/bullets
    for prefix in ("```", "### ", "## ", "# ", "- ", "* "):
        while s.startswith(prefix):
            s = s[len(prefix) :].lstrip()
    # Strip trailing code fences if present
    if s.endswith("```"):
        s = s[: -3].rstrip()
    return s


def _safe_str(val: Any, default: str = "") -> str:
    if not isinstance(val, str):
        val = str(val) if val is not None else ""
    val = _strip_markdown_like(val)
    return val if val else default


def _safe_str_list(val: Any, min_len: int = 0, max_len: Optional[int] = None) -> List[str]:
    items: List[str] = []
    if isinstance(val, list):
        for x in val:
            if isinstance(x, str) or x is not None:
                s = _strip_markdown_like(str(x))
                if s:
                    items.append(s)
    if max_len is not None and len(items) > max_len:
        items = items[:max_len]
    if len(items) < min_len:
        # Caller can decide whether to replace with fallback
        return items
    return items


def _fallback_recommendation(execution: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic, CAL FIRE–aligned fallback recommendation object used when LLM output is unusable."""
    ndvi = execution.get("mean_ndvi")
    fuel_class = execution.get("fuel_class") or "Unknown"
    veg_prox = execution.get("vegetation_proximity") or {}
    terrain = execution.get("terrain_context") or {}
    hazard = execution.get("hazard_context") or {}

    ndvi_phrase = "a noticeable vegetation signal" if isinstance(ndvi, (int, float)) else "available vegetation signals"
    fuel_phrase = f"a fuel interpretation of '{fuel_class}'" if fuel_class and fuel_class != "Unknown" else "coarse fuel interpretations"
    prox_phrase = "vegetation proximity context" if veg_prox else "general proximity patterns"
    terrain_phrase = "terrain considerations" if terrain else "basic terrain principles"
    hazard_phrase = "regional wildfire hazard context" if hazard else "general California wildfire patterns"

    summary = (
        "This California property-focused wildfire mitigation plan highlights defensible-space priorities around the home "
        "using remote vegetation signals, fuel interpretation, simple terrain context, and nearby vegetation patterns. "
        "Recommendations are aligned with official California defensible-space and home-hardening concepts and are meant "
        "to support homeowner planning, not to confirm code compliance or inspection results. All actions should be "
        "reviewed and verified on site."
    )

    zone_plan = [
        {
            "zone": "Zone 0",
            "distance": "0–5 ft",
            "objective": "Create the most ember-resistant area immediately next to the home and attached structures.",
            "recommended_actions": [
                "Regularly remove leaves, needles, bark, and other combustible debris from the first few feet next to the home, decks, stairs, and attachments.",
                "Avoid storing firewood, lumber, mulch piles, or other combustible items directly against exterior walls or under decks where embers can land.",
                "Replace or relocate highly combustible decorative items right next to the structure where practical.",
            ],
            "why_it_matters": "The first five feet nearest the home are critical for reducing ember ignition potential and direct flame contact on siding, decks, and attachments.",
            "urgency": "Immediate",
            "evidence_basis": [
                hazard_phrase,
                fuel_phrase,
                "CAL FIRE Zone 0 defensible-space concept",
            ],
            "scope_note": "Guidance in this zone is informational and does not verify official Zone 0 or defensible-space compliance. Conditions and clearances must be checked in person.",
        },
        {
            "zone": "Zone 1",
            "distance": "5–30 ft",
            "objective": "Reduce vegetation continuity and ladder-fuel pathways near the home while keeping selected plants maintained.",
            "recommended_actions": [
                "Thin and separate shrubs and small trees so they do not form continuous flame paths toward windows, vents, or eaves.",
                "Remove or reduce dead branches, leaves, and dense understory growth beneath shrubs and trees.",
                "Maintain vertical separation between surface fuels and lower tree branches to reduce ladder-fuel conditions.",
            ],
            "why_it_matters": "Managing vegetation in this zone can reduce the chance that surface fire or shrubs deliver flames directly to the home or into tree crowns.",
            "urgency": "Near-term",
            "evidence_basis": [
                ndvi_phrase,
                fuel_phrase,
                prox_phrase,
                "CAL FIRE Zones 1–2 defensible-space concepts",
            ],
            "scope_note": "Spacing and pruning needs depend on the specific plants, structures, and terrain on site. Satellite signals cannot confirm exact clearance distances; verify details in person.",
        },
        {
            "zone": "Zone 2",
            "distance": "30–100 ft",
            "objective": "Reduce broader fuel continuity and approaching fire intensity where that area is under the owner’s control and local rules allow work.",
            "recommended_actions": [
                "Where practical and lawful, reduce dense, continuous vegetation and heavy accumulations of dead material within the outer defensible-space area.",
                "Manage grasses and surface fuels so they do not form tall, continuous beds leading toward the home.",
                "Consider selective thinning or separation of shrubs and small trees to interrupt long, connected fuel pathways.",
            ],
            "why_it_matters": "Managing fuels farther from the home can lower fire intensity and ember production before fire reaches the near-home zones.",
            "urgency": "Seasonal/Ongoing",
            "evidence_basis": [
                hazard_phrase,
                terrain_phrase,
                "Regional vegetation and fuel context",
            ],
            "scope_note": "Work in this zone depends on site layout, slopes, ownership boundaries, and applicable local rules. Always comply with local requirements and verify conditions on the ground.",
        },
    ]

    rec = {
        "recommendation_summary": summary,
        "priority_bands": {
            "immediate": [
                "Reduce combustible materials and debris within the first 0–5 feet of the home.",
                "Address obvious vegetation and item continuity that could carry embers or flames directly to the structure.",
            ],
            "near_term": [
                "Thin and separate shrubs and lower branches in the 5–30 foot area.",
                "Reduce ladder fuels that could move fire from the ground into trees or structures.",
            ],
            "seasonal_ongoing": [
                "Maintain grass height and remove dead vegetation before and during fire season.",
                "Re-check near-home areas for new debris or vegetation regrowth after storms or each season.",
            ],
        },
        "zone_plan": zone_plan,
        "home_hardening_followups": [
            {
                "title": "Check ember-vulnerable features",
                "detail": "Review roofs, gutters, vents, eaves, decks, fences, and under-deck areas for places where embers and debris can accumulate and ignite.",
            },
            {
                "title": "Evaluate attachments and transitions",
                "detail": "Look at fences, gates, stairs, and other attachments that connect directly to the structure and reduce or separate combustible materials where feasible.",
            },
        ],
        "maintenance_followups": [
            {
                "title": "Seasonal vegetation maintenance",
                "detail": "Before and during fire season, remove dead material, manage grasses, and re-check spacing of key plants near the home.",
            },
            {
                "title": "Post-storm and post-wind cleanup",
                "detail": "After storms or strong winds, clear new leaves, needles, and branches from roofs, gutters, decks, and near-structure areas.",
            },
        ],
        "reasoning_trace": [
            "Vegetation and fuel signals informed emphasis on reducing fuel continuity near the home.",
            "Proximity of potential fuels to the structure informed focus on ember-resistant Zone 0 and Zone 1 actions.",
            "General terrain and regional wildfire context informed attention to broader fuel continuity and seasonal maintenance.",
        ],
        "limitations": [
            "This is a California-focused informational planning output, not an official inspection.",
            "It does not determine legal compliance, code-enforcement status, or insurance eligibility.",
            "Recommendations are based on remote and structured signals and must be verified on site.",
            "Local requirements, ownership boundaries, and professional judgment should guide any work.",
        ],
    }
    return rec


def _normalize_recommendation(raw: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce an arbitrary LLM object into the required recommendation schema, falling back when necessary."""
    if not isinstance(raw, dict):
        return fallback

    def _zone_key(z: str) -> str:
        z = (z or "").strip()
        if z.startswith("Zone 0"):
            return "Zone 0"
        if z.startswith("Zone 1"):
            return "Zone 1"
        if z.startswith("Zone 2"):
            return "Zone 2"
        return ""

    # Base from fallback so all required keys exist.
    out = json.loads(json.dumps(fallback))

    out["recommendation_summary"] = _safe_str(
        raw.get("recommendation_summary"),
        default=fallback.get("recommendation_summary", ""),
    )

    pb_raw = raw.get("priority_bands") or {}
    if isinstance(pb_raw, dict):
        for band in ("immediate", "near_term", "seasonal_ongoing"):
            items = _safe_str_list(pb_raw.get(band), max_len=5)
            if items:
                out["priority_bands"][band] = items

    # Zone plan: require exactly Zone 0/1/2. Prefer LLM content when usable, otherwise fallback zones.
    zones_by_key: Dict[str, Dict[str, Any]] = {}
    zp_raw = raw.get("zone_plan") or []
    if isinstance(zp_raw, list):
        for item in zp_raw:
            if not isinstance(item, dict):
                continue
            key = _zone_key(item.get("zone", ""))
            if not key or key in zones_by_key:
                continue
            zones_by_key[key] = item

    normalized_zones: List[Dict[str, Any]] = []
    for fb_zone in fallback.get("zone_plan", []):
        key = fb_zone.get("zone")
        candidate = zones_by_key.get(key, {})
        merged: Dict[str, Any] = {}
        merged["zone"] = key
        merged["distance"] = _safe_str(
            candidate.get("distance"),
            default=_safe_str(fb_zone.get("distance", "")),
        )
        merged["objective"] = _safe_str(
            candidate.get("objective"),
            default=_safe_str(fb_zone.get("objective", "")),
        )
        recs = _safe_str_list(candidate.get("recommended_actions"), max_len=6)
        if not recs:
            recs = _safe_str_list(fb_zone.get("recommended_actions"), max_len=6)
        merged["recommended_actions"] = recs
        merged["why_it_matters"] = _safe_str(
            candidate.get("why_it_matters"),
            default=_safe_str(fb_zone.get("why_it_matters", "")),
        )
        urgency = _safe_str(candidate.get("urgency"), default=_safe_str(fb_zone.get("urgency", "")))
        if urgency not in ("Immediate", "Near-term", "Seasonal/Ongoing"):
            urgency = _safe_str(fb_zone.get("urgency", ""))
        merged["urgency"] = urgency or "Near-term"
        ev = _safe_str_list(candidate.get("evidence_basis"), max_len=5)
        if not ev:
            ev = _safe_str_list(fb_zone.get("evidence_basis"), max_len=5)
        merged["evidence_basis"] = ev
        merged["scope_note"] = _safe_str(
            candidate.get("scope_note"),
            default=_safe_str(fb_zone.get("scope_note", "")),
        )
        normalized_zones.append(merged)
    if len(normalized_zones) == 3:
        out["zone_plan"] = normalized_zones

    hh_raw = raw.get("home_hardening_followups") or []
    home_items: List[Dict[str, Any]] = []
    if isinstance(hh_raw, list):
        for item in hh_raw:
            if not isinstance(item, dict):
                continue
            title = _safe_str(item.get("title"))
            detail = _safe_str(item.get("detail"))
            if title and detail:
                home_items.append({"title": title, "detail": detail})
    if 2 <= len(home_items) <= 5:
        out["home_hardening_followups"] = home_items

    maint_raw = raw.get("maintenance_followups") or []
    maint_items: List[Dict[str, Any]] = []
    if isinstance(maint_raw, list):
        for item in maint_raw:
            if not isinstance(item, dict):
                continue
            title = _safe_str(item.get("title"))
            detail = _safe_str(item.get("detail"))
            if title and detail:
                maint_items.append({"title": title, "detail": detail})
    if 2 <= len(maint_items) <= 5:
        out["maintenance_followups"] = maint_items

    rt_raw = _safe_str_list(raw.get("reasoning_trace"), max_len=6)
    if 3 <= len(rt_raw) <= 6:
        out["reasoning_trace"] = rt_raw

    lim_raw = _safe_str_list(raw.get("limitations"), max_len=6)
    if 3 <= len(lim_raw) <= 6:
        out["limitations"] = lim_raw

    return out


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
    Pipeline:
      - Planner LLM produces an execution spec (JSON).
      - Plan is normalized and validated.
      - Tool arguments are derived and validated.
      - For Baseline (Free Tier): a rule-based executor/orchestrator runs tools via TOOL_REGISTRY,
        then a separate synthesis LLM call generates a structured Baseline report JSON.
      - For Full (Paid Tier): the legacy executor and reporter pipeline is used.

    When address/lat/lng are provided (e.g. from Google Places UI), planner and executor use them;
    geocoding is skipped when valid coordinates are provided.
    """
    start_ts = time.time()
    budget_env = os.getenv("ASSESS_BUDGET_SEC")
    budget_sec: Optional[float] = None
    try:
        if budget_env and str(budget_env).strip():
            budget_sec = float(budget_env)
        elif os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
            # Render free tier commonly enforces ~30s request timeouts at the proxy.
            budget_sec = 25.0
    except (TypeError, ValueError):
        budget_sec = None

    def _remaining_sec() -> Optional[float]:
        if budget_sec is None:
            return None
        return budget_sec - (time.time() - start_ts)

    def _budget_low(min_remaining: float = 5.0) -> bool:
        rem = _remaining_sec()
        return rem is not None and rem <= float(min_remaining)

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

    # Special-case Baseline (Free Tier): planner + deterministic tools + structured synthesis LLM.
    if plan.get("request_type") == "baseline_free_tier":
        if not args_ok:
            return {
                "plan": plan,
                "tool_args": tool_args,
                "validation": {
                    "passed": False,
                    "reasons": plan_reasons + args_reasons,
                },
                "execution": {},
                "final_response": "Baseline request blocked by validation checks.",
            }

        baseline_result = execute_baseline_workflow(
            plan,
            address=address,
            lat=provided_lat,
            lng=provided_lng,
            tool_args=tool_args,
            llm_client=client,
        )
        status = baseline_result.get("status")
        execution = baseline_result.get("execution_summary") or {}
        final_report = baseline_result.get("final_report") or {}

        def _baseline_plaintext_from_report(report: Dict[str, Any]) -> str:
            if not isinstance(report, dict):
                return ""
            parts = []
            summary = report.get("summary")
            if isinstance(summary, str) and summary.strip():
                parts.append(summary.strip())
            sections = report.get("sections") or {}
            order = [
                ("california_scope_validation", "California scope validation"),
                ("fire_hazard_context", "Fire hazard context"),
                ("terrain_context", "Terrain context"),
                ("regional_vegetation_context", "Regional vegetation context"),
                ("limitations", "Limitations"),
            ]
            for key, label in order:
                text = sections.get(key)
                if isinstance(text, str) and text.strip():
                    parts.append(f"{label}: {text.strip()}")
            return "\n\n".join(parts).strip()

        final_text = _baseline_plaintext_from_report(final_report) or (
            "Baseline (Free Tier) California wildfire overview is ready."
        )

        if status != "completed":
            return {
                "plan": plan,
                "tool_args": tool_args,
                "validation": {
                    "passed": False,
                    "reasons": ["Baseline executor could not complete all required steps."],
                },
                "execution": execution,
                "final_response": "Baseline request could not be completed (for example, due to missing or invalid location data).",
                "baseline_workflow": baseline_result,
            }

        return {
            "plan": plan,
            "tool_args": tool_args,
            "validation": {"passed": True, "reasons": []},
            "execution": execution,
            "final_response": final_text,
            "baseline_workflow": baseline_result,
        }

    # 3. Validator LLM (Full tier and other non-baseline flows)
    if _budget_low():
        validator_llm = _fallback_validation()
        validator_llm["reasons"] = list(validator_llm.get("reasons") or []) + ["Skipped validator LLM due to request time budget."]
    else:
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

    # 4. Executor (Full tier): run the plan steps using internal tool identifiers
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
            if os.getenv("DISABLE_NDVI") in ("1", "true", "TRUE", "yes", "YES"):
                execution["mean_ndvi"] = None
                execution["evidence"]["ndvi"] = {
                    "source": "disabled",
                    "reason": "NDVI disabled by DISABLE_NDVI env var.",
                }
                continue
            if _budget_low(min_remaining=8.0):
                execution["mean_ndvi"] = None
                execution["evidence"]["ndvi"] = {
                    "source": "skipped",
                    "reason": "NDVI skipped due to request time budget.",
                }
                continue
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
            # Dedicated CAL FIRE–aligned recommendation LLM step (structured JSON only).
            rec_input = {
                "address": execution.get("address"),
                "california_validation": {
                    "in_california": True,
                    "method": "coarse_bounding_box",
                },
                "hazard_context": execution.get("hazard_context"),
                "terrain_context": execution.get("terrain_context"),
                "ndvi": execution.get("mean_ndvi"),
                "fuel_class": execution.get("fuel_class"),
                "slope_analysis": execution.get("property_slope"),
                "vegetation_proximity": execution.get("vegetation_proximity"),
                "regional_vegetation_context": execution.get("regional_vegetation_context"),
                "photo_analysis": execution.get("photo_analysis"),
                "plan_metadata": {
                    "tier": plan.get("request_type"),
                    "analysis_modules": plan.get("analysis_modules"),
                },
            }
            fallback_rec = _fallback_recommendation(execution)
            if _budget_low(min_remaining=8.0):
                execution["calfire_recommendations"] = fallback_rec
                execution.setdefault("evidence", {}).setdefault("warnings", []).append(
                    "Skipped CAL FIRE recommendation LLM due to request time budget."
                )
            elif not client.is_configured():
                execution["calfire_recommendations"] = fallback_rec
            else:
                user_payload = json.dumps(rec_input, default=str, indent=2)
                # First attempt
                first = client.chat_json(
                    CALFIRE_RECOMMENDATION_SYSTEM,
                    user_payload,
                    fallback=fallback_rec,
                )
                rec = _normalize_recommendation(first, fallback=fallback_rec)
                # If the normalized result still looks like the untouched fallback and the raw was clearly not a dict,
                # attempt a single repair call.
                if (not isinstance(first, dict)) and (not _budget_low(min_remaining=10.0)):
                    repair_prompt = json.dumps(
                        {
                            "input": rec_input,
                            "previous_output": first,
                            "instruction": "Repair the previous output to exactly match the required JSON schema. Return only the corrected JSON object.",
                        },
                        default=str,
                        indent=2,
                    )
                    second = client.chat_json(
                        CALFIRE_RECOMMENDATION_SYSTEM,
                        repair_prompt,
                        fallback=fallback_rec,
                    )
                    rec = _normalize_recommendation(second, fallback=fallback_rec)
                execution["calfire_recommendations"] = rec

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
    if _budget_low():
        final_response = fallback_text + " (Some narrative synthesis steps were skipped due to request time budget.)"
    else:
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
