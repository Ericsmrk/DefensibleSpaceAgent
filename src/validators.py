from __future__ import annotations

from typing import Dict, List, Tuple

ALLOWED_TOOLS = {"geocode_google", "compute_mean_ndvi", "classify_fuel", None}
REQUIRED_PLAN_KEYS = {"domain", "user_goal", "steps"}
REQUIRED_TOOL_KEYS = {"address", "buffer_m", "start", "end", "cloud_pct"}


def validate_plan(plan: Dict) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    missing = REQUIRED_PLAN_KEYS - set(plan.keys())
    if missing:
        reasons.append(f"missing plan keys: {sorted(missing)}")

    steps = plan.get("steps", [])
    if not isinstance(steps, list) or not steps:
        reasons.append("steps must be a non-empty list")
    else:
        for idx, step in enumerate(steps):
            tool = step.get("tool")
            if tool not in ALLOWED_TOOLS:
                reasons.append(f"step {idx} uses disallowed tool: {tool}")

    return (len(reasons) == 0, reasons)


def validate_tool_args(args: Dict) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    missing = REQUIRED_TOOL_KEYS - set(args.keys())
    if missing:
        reasons.append(f"missing tool args keys: {sorted(missing)}")
        return False, reasons

    buffer_m = args.get("buffer_m")
    cloud_pct = args.get("cloud_pct")

    if not isinstance(buffer_m, int) or buffer_m <= 0 or buffer_m > 500:
        reasons.append("buffer_m must be int in range 1..500")
    if not isinstance(cloud_pct, int) or cloud_pct < 0 or cloud_pct > 100:
        reasons.append("cloud_pct must be int in range 0..100")

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
