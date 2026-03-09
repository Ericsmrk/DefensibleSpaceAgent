from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from typing import Optional, Tuple


def geocode_google(address: str) -> Tuple[Optional[float], Optional[float], dict]:
    api_key = os.getenv("GOOGLE_MAPS_KEY")
    if not api_key:
        # No API key configured: do not fabricate coordinates. Signal to callers that
        # geocoding is unavailable so they can fail or degrade gracefully.
        return None, None, {
            "status": "MISSING_API_KEY",
            "source": "google",
            "error": "GOOGLE_MAPS_KEY not set; geocoding disabled",
        }

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    query = urllib.parse.urlencode({"address": address, "key": api_key})
    req = urllib.request.Request(f"{url}?{query}", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("status") != "OK" or not data.get("results"):
        return None, None, {"status": data.get("status", "UNKNOWN"), "source": "google"}

    loc = data["results"][0]["geometry"]["location"]
    return float(loc["lat"]), float(loc["lng"]), {"status": "OK", "source": "google"}


def compute_mean_ndvi(
    lat: float,
    lon: float,
    buffer_m: int = 100,
    start: str = "2024-06-01",
    end: str = "2024-09-01",
    cloud_pct: int = 20,
) -> Tuple[Optional[float], dict]:
    # NDVI requires an external satellite imagery provider (e.g. Sentinel, Landsat).
    # This build does not call any third-party NDVI API and will not fabricate values.
    # Callers should treat the None result as "no NDVI data available" and surface that clearly.
    meta = {
        "source": "unavailable",
        "window": [start, end],
        "cloud_pct": cloud_pct,
        "reason": "NDVI computation requires an external satellite data provider and is not configured.",
        "lat": lat,
        "lon": lon,
        "buffer_m": buffer_m,
    }
    return None, meta


def classify_fuel(ndvi: Optional[float]) -> str:
    if ndvi is None:
        return "No Data"
    if ndvi >= 0.6:
        return "High Vegetation (High Fuel Load)"
    if ndvi >= 0.3:
        return "Moderate Vegetation"
    if ndvi >= 0.1:
        return "Sparse Vegetation"
    return "Minimal Vegetation"
