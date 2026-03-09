from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from .llm_client import LLMClient
from .prompts import BASELINE_SYNTHESIS_SYSTEM
from .schemas import (
    BaselineToolContext,
    ToolResult,
)
from .tools import geocode_google


def _in_ca_bounds(lat: float, lon: float) -> bool:
    """
    Approximate geographic bounding box for California.

    This is a coarse safety check only and is NOT a substitute for
    authoritative jurisdiction or hazard designations.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    return 32.0 <= lat_f <= 42.5 and -124.7 <= lon_f <= -114.0


def resolve_location(context: BaselineToolContext) -> ToolResult:
    """
    Resolve the location for the request.

    - If coordinates are already present on the context, they are reused.
    - Otherwise, geocodes the address using Google Maps (when configured).
    """
    if context.lat is not None and context.lng is not None:
        data = {
            "coordinates": {"lat": context.lat, "lng": context.lng},
            "source": "provided",
        }
        context.location_metadata["geocode"] = {"status": "OK", "source": "provided"}
        return ToolResult(
            tool_name="resolve_location",
            success=True,
            data=data,
            sources=["provided_coordinates"],
            limitations=[
                "Coordinates were supplied by the client; no additional geocoding was performed."
            ],
        )

    address = (context.address or "").strip()
    if not address:
        return ToolResult(
            tool_name="resolve_location",
            success=False,
            data={},
            sources=[],
            limitations=[
                "No address was available for geocoding; cannot resolve location.",
            ],
        )

    lat, lon, meta = geocode_google(address)
    context.location_metadata["geocode"] = meta or {}

    if lat is None or lon is None:
        return ToolResult(
            tool_name="resolve_location",
            success=False,
            data={"coordinates": None, "geocode_meta": meta},
            sources=["google_geocoding"],
            limitations=[
                "Google geocoding did not return a usable coordinate for this address.",
                "Without coordinates the Baseline analysis cannot proceed.",
            ],
        )

    context.lat = float(lat)
    context.lng = float(lon)

    return ToolResult(
        tool_name="resolve_location",
        success=True,
        data={"coordinates": {"lat": context.lat, "lng": context.lng}, "geocode_meta": meta},
        sources=["google_geocoding"],
        limitations=[
            "Geocoding is approximate and may not align exactly with parcel centroids.",
            "Parcel boundary data is not integrated in this build.",
        ],
    )


def validate_california_scope(context: BaselineToolContext) -> ToolResult:
    """
    Confirm that the resolved location is within California.

    Uses:
      - Coordinates (coarse CA bounding box)
      - Geocoding metadata when available (state, county, city)
    """
    lat, lng = context.lat, context.lng
    meta = context.location_metadata.get("geocode") or {}

    if lat is None or lng is None:
        return ToolResult(
            tool_name="validate_california_scope",
            success=False,
            data={
                "in_california": False,
                "reason": "Missing coordinates; cannot validate California scope.",
            },
            sources=[],
            limitations=[
                "California-only validation requires at least coarse coordinates.",
            ],
        )

    state = (meta.get("state") or "").strip() or None
    state_code = (meta.get("state_code") or "").upper() or None
    in_box = _in_ca_bounds(lat, lng)
    looks_ca = in_box and (state_code in (None, "", "CA") or (state or "").upper() == "CALIFORNIA")

    county = meta.get("county")
    city = meta.get("city")
    resolved_address = meta.get("formatted_address") or context.address

    method = "coordinate_bounding_box"
    if meta:
        method = "geocoding_plus_bounding_box"

    data: Dict[str, Any] = {
        "in_california": looks_ca,
        "state": state,
        "state_code": state_code,
        "county": county,
        "city": city,
        "resolved_address": resolved_address,
        "coordinates": {"lat": lat, "lng": lng},
        "validation_method": method,
        "reason": "Location appears inside a coarse California bounding box."
        if looks_ca
        else "Location appears to be outside California based on coarse bounds and/or basic metadata.",
    }

    limitations = [
        "This check uses a coarse geographic bounding box, not official jurisdiction boundaries.",
        "Official CAL FIRE Fire Hazard Severity Zone designations are NOT integrated in this build.",
    ]

    return ToolResult(
        tool_name="validate_california_scope",
        success=looks_ca,
        data=data,
        sources=["coordinate_bounding_box_check"] + (["google_geocoding"] if meta else []),
        limitations=limitations,
    )


def gather_hazard_context(context: BaselineToolContext) -> ToolResult:
    """
    Gather coarse regional wildfire hazard context.

    This is intentionally high-level and does NOT provide parcel-specific
    hazard designations or FHSZ labels.
    """
    lat, lng = context.lat, context.lng
    if lat is None or lng is None:
        return ToolResult(
            tool_name="gather_hazard_context",
            success=False,
            data={
                "summary": "No coordinates available; hazard context cannot be localized.",
                "regional_wildfire_relevance": "unknown",
                "hazard_region_name": None,
                "nearby_context_summary": None,
                "supported_notes": [],
            },
            sources=[],
            limitations=[
                "Hazard context requires at least approximate coordinates.",
            ],
        )

    summary = (
        "Regional wildfire exposure is a concern in many parts of inland California where wildland fuels and "
        "nearby communities overlap. This Baseline overview does not assign a parcel-level hazard rating."
    )

    data: Dict[str, Any] = {
        "summary": summary,
        "regional_wildfire_relevance": "present",
        "hazard_region_name": None,
        "nearby_context_summary": (
            "This build does not query official Fire Hazard Severity Zone maps or recent fire perimeters for this address."
        ),
        "supported_notes": [
            "Large wildfires have occurred across many California regions in recent decades.",
            "Local exposure depends on nearby wildland fuels, terrain, and wind patterns, which are only coarsely captured here.",
        ],
    }

    limitations = [
        "No parcel-level hazard map (e.g., official Fire Hazard Severity Zone) is integrated in this build.",
        "Historical fire perimeter or ignition data is not queried in this Baseline implementation.",
    ]

    return ToolResult(
        tool_name="gather_hazard_context",
        success=True,
        data=data,
        sources=["general_california_wildfire_patterns"],
        limitations=limitations,
    )


def gather_terrain_context(context: BaselineToolContext) -> ToolResult:
    """
    Provide a simple terrain context placeholder.

    No DEM or slope model is currently integrated; this call only provides
    qualitative guidance tied to the presence of hills and slopes in general.
    """
    lat, lng = context.lat, context.lng
    summary = (
        "Terrain conditions such as slopes, ridges, and canyons can strongly influence fire spread, with fire "
        "typically moving faster upslope and along aligned drainages. This Baseline overview does not compute "
        "parcel-specific slope or aspect for the property."
    )

    data: Dict[str, Any] = {
        "summary": summary,
        "terrain_setting": None,
        "elevation_ft": None,
        "terrain_summary": summary,
        "supported_notes": [
            "Fire can accelerate upslope and follow drainages or aligned canyons.",
            "Local slope and aspect for this specific parcel are not calculated in this Baseline build.",
        ],
        "coordinates_used": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
    }

    limitations = [
        "No digital elevation model (DEM) or high-resolution terrain dataset is connected in this build.",
        "Slope, aspect, and local landform are not computed for this specific parcel.",
    ]

    return ToolResult(
        tool_name="gather_terrain_context",
        success=True,
        data=data,
        sources=["generic_terrain_fire_behavior_principles"],
        limitations=limitations,
    )


def gather_regional_vegetation_context(context: BaselineToolContext) -> ToolResult:
    """
    Provide a simple regional vegetation / land-cover context placeholder.

    This does NOT perform parcel-level fuel mapping or NDVI analysis.
    """
    lat, lng = context.lat, context.lng
    summary = (
        "Many parts of California feature grasses, shrubs, and forested areas that can act as wildfire fuels. "
        "This Baseline overview describes typical regional vegetation patterns only, not parcel-specific fuel conditions."
    )

    data: Dict[str, Any] = {
        "summary": summary,
        "vegetation_setting": None,
        "dominant_patterns": None,
        "land_cover_context": (
            "This build does not query detailed land-cover or fuel-type datasets for this address."
        ),
        "supported_notes": [
            "Fine fuels such as dry grasses and leaf litter can ignite easily and carry fire quickly.",
            "Shrubs and small trees can act as ladder fuels between surface fuels and tree canopies.",
        ],
        "coordinates_used": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
    }

    limitations = [
        "No land-cover or vegetation classification dataset is queried in this Baseline implementation.",
        "NDVI or other remote-sensing vegetation indices are not used for parcel-specific fuel estimates here.",
    ]

    return ToolResult(
        tool_name="gather_regional_vegetation_context",
        success=True,
        data=data,
        sources=["generic_california_vegetation_patterns"],
        limitations=limitations,
    )


def generate_baseline_report(
    context: BaselineToolContext,
    llm_client: LLMClient,
) -> ToolResult:
    """
    Synthesize the final Baseline report using an OpenAI call.

    The synthesis strictly uses the structured tool outputs assembled in the context and
    returns a structured JSON report that is easy for the UI to render.
    """
    # Prepare a compact view of tool outputs keyed by tool_name for the LLM.
    tools_payload: Dict[str, Any] = {}
    for tool_result in context.step_outputs.values():
        tools_payload[tool_result.tool_name] = {
            "success": tool_result.success,
            "data": tool_result.data,
            "sources": tool_result.sources,
            "limitations": tool_result.limitations,
        }

    user_payload = {
        "address": context.address,
        "coordinates": {"lat": context.lat, "lng": context.lng},
        "planner_metadata": {
            "tier": context.execution_spec.request_type,
            "assessment_mode": context.execution_spec.assessment_mode,
            "analysis_modules": context.execution_spec.analysis_modules,
        },
        "tool_outputs": tools_payload,
    }

    def _fallback_synthesis() -> Dict[str, Any]:
        """Deterministic, cautious fallback when the LLM is unavailable or returns invalid JSON."""

        addr = context.address or "this address"
        v = tools_payload.get("validate_california_scope", {})
        v_data = v.get("data") or {}
        in_ca = bool(v_data.get("in_california"))
        city = v_data.get("city")
        county = v_data.get("county")

        loc_bits: List[str] = []
        if city:
            loc_bits.append(str(city))
        if county:
            loc_bits.append(str(county))
        if in_ca:
            loc_bits.append("California")
        loc_phrase = ", ".join(loc_bits) if loc_bits else "a location in California"

        summary = (
            f"This Baseline overview provides an address-level look at wildfire context for {addr}, "
            f"with emphasis on California scope, regional hazard, terrain, and vegetation."
        )

        sections = {
            "california_scope_validation": (
                "Available information suggests this address is within California, based on coarse coordinate checks "
                "and any geocoding metadata that may be available. This validation does not use official jurisdictional "
                "or Fire Hazard Severity Zone designations."
                if in_ca
                else "The system cannot confidently confirm that this address is within California, so all other sections "
                "should be treated as highly preliminary."
            ),
            "fire_hazard_context": (
                "Large wildfires have affected many parts of California in recent decades, especially where wildland fuels "
                "and communities overlap. Because this Baseline build does not query specific hazard layers for "
                f"{loc_phrase}, it cannot provide a parcel-level hazard rating."
            ),
            "terrain_context": (
                "Terrain such as slopes, ridges, and canyons can strongly influence fire spread, often allowing fire to move "
                "faster upslope or along aligned drainages. This Baseline overview does not compute slope or aspect for the "
                "specific property."
            ),
            "regional_vegetation_context": (
                "Typical California vegetation patterns include grasses, shrubs, and forested areas that can act as wildfire fuels. "
                "This Baseline result does not include a detailed fuel map for the property itself or its immediate surroundings."
            ),
            "limitations": (
                "This is an address-level Baseline overview only. It does not include parcel-level hazard ratings, NDVI or fuel "
                "classification, detailed terrain modeling, or vegetation proximity analysis. It should not be used as a substitute "
                "for an engineered site-specific wildfire or defensible-space study."
            ),
        }

        evidence_used = {
            "california_scope_validation": [
                "Coarse coordinate bounding-box check for California extent.",
            ],
            "fire_hazard_context": [
                "General knowledge that many California regions have experienced large wildfires.",
            ],
            "terrain_context": [
                "General fire behavior principles relating to slope and canyons.",
            ],
            "regional_vegetation_context": [
                "General understanding of common California vegetation types and their role as wildfire fuels.",
            ],
        }

        return {
            "report_title": "Baseline Wildfire Overview",
            "summary": summary,
            "sections": sections,
            "evidence_used": evidence_used,
        }

    serialized = json.dumps(user_payload, default=str, indent=2)
    user_message = (
        "You are synthesizing a California Baseline wildfire overview for one address.\n\n"
        "Use ONLY the structured tool outputs provided below.\n\n"
        "STRUCTURED_INPUT:\n"
        f"{serialized}\n"
    )

    if not llm_client.is_configured():
        synthesis = _fallback_synthesis()
    else:
        raw = llm_client.chat_json(
            BASELINE_SYNTHESIS_SYSTEM,
            user_message,
            fallback=_fallback_synthesis(),
        )

        # Validate and coerce into the expected schema; fall back if structure is not usable.
        base = _fallback_synthesis()
        if not isinstance(raw, dict):
            synthesis = base
        else:
            sections_raw = raw.get("sections") or {}
            evidence_raw = raw.get("evidence_used") or {}

            def _s(val: Any, default: str) -> str:
                return str(val).strip() if isinstance(val, str) and val.strip() else default

            def _lst(val: Any) -> List[str]:
                if isinstance(val, list):
                    return [str(x) for x in val if isinstance(x, str) and x.strip()]
                return []

            synthesis = {
                "report_title": _s(raw.get("report_title"), base["report_title"]),
                "summary": _s(raw.get("summary"), base["summary"]),
                "sections": {
                    "california_scope_validation": _s(
                        sections_raw.get("california_scope_validation"),
                        base["sections"]["california_scope_validation"],
                    ),
                    "fire_hazard_context": _s(
                        sections_raw.get("fire_hazard_context"),
                        base["sections"]["fire_hazard_context"],
                    ),
                    "terrain_context": _s(
                        sections_raw.get("terrain_context"),
                        base["sections"]["terrain_context"],
                    ),
                    "regional_vegetation_context": _s(
                        sections_raw.get("regional_vegetation_context"),
                        base["sections"]["regional_vegetation_context"],
                    ),
                    "limitations": _s(
                        sections_raw.get("limitations"),
                        base["sections"]["limitations"],
                    ),
                },
                "evidence_used": {
                    "california_scope_validation": _lst(
                        evidence_raw.get("california_scope_validation")
                    )
                    or base["evidence_used"]["california_scope_validation"],
                    "fire_hazard_context": _lst(evidence_raw.get("fire_hazard_context"))
                    or base["evidence_used"]["fire_hazard_context"],
                    "terrain_context": _lst(evidence_raw.get("terrain_context"))
                    or base["evidence_used"]["terrain_context"],
                    "regional_vegetation_context": _lst(
                        evidence_raw.get("regional_vegetation_context")
                    )
                    or base["evidence_used"]["regional_vegetation_context"],
                },
            }

    return ToolResult(
        tool_name="generate_baseline_report",
        success=True,
        data=synthesis,
        sources=["openai_chat_completion"] if llm_client.is_configured() else [],
        limitations=[
            "This Baseline report is intentionally limited to address-level regional context.",
            "Parcel-specific environmental data and CAL FIRE official designations are not used here.",
        ],
    )


TOOL_REGISTRY: Dict[str, Callable[..., ToolResult]] = {
    "resolve_location": resolve_location,
    "validate_california_scope": validate_california_scope,
    "gather_hazard_context": gather_hazard_context,
    "gather_terrain_context": gather_terrain_context,
    "gather_regional_vegetation_context": gather_regional_vegetation_context,
    "generate_baseline_report": generate_baseline_report,
}

