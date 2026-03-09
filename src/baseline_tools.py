from __future__ import annotations

import json
from typing import Any, Callable, Dict

from .llm_client import LLMClient
from .prompts import BASELINE_SYNTHESIS_SYSTEM
from .schemas import (
    BaselineToolContext,
    FinalBaselineReport,
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
            data={"reason": "Missing coordinates; cannot validate California scope."},
            sources=[],
            limitations=[
                "California-only validation requires at least coarse coordinates.",
            ],
        )

    state_code = (meta.get("state_code") or meta.get("state") or "").upper()
    in_box = _in_ca_bounds(lat, lng)
    looks_ca = in_box and (not state_code or "CA" in state_code or "CALIFORNIA" in state_code)

    county = meta.get("county")
    city = meta.get("city")

    data: Dict[str, Any] = {
        "is_california": looks_ca,
        "coordinates": {"lat": lat, "lng": lng},
        "address": context.address,
        "state_code": state_code or None,
        "county": county,
        "city": city,
        "reason": "Location appears inside a coarse California bounding box."
        if looks_ca
        else "Location appears to be outside California based on coarse bounds and/or metadata.",
    }

    limitations = [
        "This check uses a coarse geographic bounding box, not official jurisdiction boundaries.",
        "Official CAL FIRE Fire Hazard Severity Zone designations are NOT integrated in this build.",
    ]

    return ToolResult(
        tool_name="validate_california_scope",
        success=looks_ca,
        data=data,
        sources=["coordinate_bounding_box_check"]
        + (["google_geocoding"] if meta else []),
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
            data={"summary": "No coordinates available; hazard context cannot be localized."},
            sources=[],
            limitations=[
                "Hazard context requires at least approximate coordinates.",
            ],
        )

    summary = (
        "Regional California wildfire hazard is generally elevated in many wildland-urban interface areas, "
        "driven by seasonal dryness, accumulated fuels, and wind-driven fire spread. This Baseline overview "
        "describes regional patterns only and does not assign a parcel-level hazard rating."
    )

    data: Dict[str, Any] = {
        "summary": summary,
        "notes": [
            "Recent decades have seen frequent large wildfires across many parts of California.",
            "Exposure is influenced by nearby wildland fuels, topography, and prevailing wind patterns.",
        ],
    }

    limitations = [
        "No parcel-level hazard map (e.g., official Fire Hazard Severity Zone) is integrated in this build.",
        "Historical fire perimeter data is not queried in this Baseline implementation.",
    ]

    return ToolResult(
        tool_name="gather_hazard_context",
        success=True,
        data=data,
        sources=["regional_california_wildfire_patterns"],
        limitations=limitations,
    )


def gather_terrain_context(context: BaselineToolContext) -> ToolResult:
    """
    Provide a simple terrain context placeholder.

    No DEM or slope model is currently integrated; this call only provides
    qualitative guidance tied to the presence of hills and slopes in general.
    """
    lat, lng = context.lat, context.lng
    data: Dict[str, Any] = {
        "summary": (
            "Terrain conditions such as slopes, ridges, and canyons can strongly influence fire spread, with "
            "fire typically moving faster upslope and along aligned drainages. This Baseline overview does not "
            "compute parcel-specific slope or aspect for the property."
        ),
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
        "Many parts of California feature a mix of grasses, shrubs, and forested areas that can act as "
        "wildfire fuels. In wildland-urban interface settings, ornamental landscaping and unmanaged vegetation "
        "can also contribute to ember exposure and flame contact. This Baseline overview only describes "
        "typical regional vegetation patterns, not parcel-specific fuel conditions."
    )

    data: Dict[str, Any] = {
        "summary": summary,
        "coordinates_used": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
        "notes": [
            "Fine fuels like dry grasses and leaf litter can ignite easily and carry fire quickly.",
            "Shrubs and small trees can create ladder fuels that move fire into taller canopies.",
        ],
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

    The synthesis strictly uses the structured tool outputs assembled in the context.
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
        "plan": {
            "request_type": context.execution_spec.request_type,
            "assessment_mode": context.execution_spec.assessment_mode,
            "analysis_modules": context.execution_spec.analysis_modules,
        },
        "tool_outputs": tools_payload,
    }

    serialized = json.dumps(user_payload, default=str, indent=2)

    user_message = (
        "You are synthesizing a California Baseline wildfire overview for one address.\n\n"
        "Use ONLY the structured tool outputs provided below. Do not invent parcel-specific facts, "
        "measurements, or hazard designations.\n\n"
        "STRUCTURED_INPUT:\n"
        f"{serialized}\n"
    )

    fallback_text = (
        "Baseline California wildfire overview based on regional hazard, terrain, and vegetation context. "
        "Detailed parcel-specific analyses (NDVI, fuel class, slope, proximity) are not included in this free tier."
    )

    if not llm_client.is_configured():
        report_text = fallback_text
    else:
        report_text = llm_client.chat_text(
            BASELINE_SYNTHESIS_SYSTEM,
            user_message,
            fallback=fallback_text,
        )

    report = FinalBaselineReport(
        tier="baseline_free_tier",
        text=report_text,
        sections={},
    )

    return ToolResult(
        tool_name="generate_baseline_report",
        success=True,
        data={"report_text": report.text},
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

