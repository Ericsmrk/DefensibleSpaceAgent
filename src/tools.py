from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import ee  # type: ignore[import]
except Exception:  # pragma: no cover - optional dependency
    ee = None

# Last Earth Engine init error, for startup message.
_last_ee_error: Optional[str] = None


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

    result = data["results"][0]
    loc = result["geometry"]["location"]

    meta: dict = {"status": "OK", "source": "google"}
    meta["formatted_address"] = result.get("formatted_address")

    # Extract lightweight administrative context (state, county, city) when available.
    components = result.get("address_components") or []
    for comp in components:
        types = comp.get("types") or []
        long_name = comp.get("long_name")
        short_name = comp.get("short_name")
        if "administrative_area_level_1" in types:
            meta["state"] = long_name
            meta["state_code"] = short_name
        elif "administrative_area_level_2" in types:
            meta["county"] = long_name
        elif "locality" in types or "postal_town" in types or "sublocality" in types:
            # Use the first reasonable city/locality-like component we find.
            if "city" not in meta:
                meta["city"] = long_name

    return float(loc["lat"]), float(loc["lng"]), meta


def _ee_credentials_path() -> str:
    """Path to the Earth Engine credentials file (same as earthengine authenticate)."""
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".config", "earthengine", "credentials")


def _ensure_ee_initialized() -> bool:
    """
    Best-effort initialization for Google Earth Engine.

    This assumes that service account or user credentials have already been
    configured in the environment where the app is running. If initialization
    fails, callers should treat NDVI as unavailable.
    """
    global _last_ee_error
    if ee is None:
        return False
    try:
        ee.Number(1).getInfo()
        return True
    except Exception:
        pass
    _last_ee_error = None
    try:
        ee.Initialize()
        ee.Number(1).getInfo()
        return True
    except Exception as e:
        _last_ee_error = str(e)
        pass
    # Fallback: load credentials from explicit path (fixes Windows/IDE when
    # expanduser('~') doesn't match where earthengine authenticate wrote the file).
    cred_path = _ee_credentials_path()
    if not os.path.isfile(cred_path):
        _last_ee_error = f"credentials not found at {cred_path}"
        return False
    try:
        from google.oauth2 import credentials as credentials_lib

        with open(cred_path, encoding="utf-8") as f:
            stored = json.load(f)
        refresh_token = stored.get("refresh_token")
        if not refresh_token:
            _last_ee_error = "no refresh_token in credentials file; run earthengine authenticate again"
            return False
        token_uri = "https://oauth2.googleapis.com/token"
        args = {
            "token": None,
            "refresh_token": refresh_token,
            "token_uri": token_uri,
            "client_id": stored.get("client_id", "517222506229-vsmmajv00ul0bs7p89v5m89qs8eb9359.apps.googleusercontent.com"),
            "client_secret": stored.get("client_secret", "RUP0RZ6e0pPhDzsqIJ7KlNd1"),
            "scopes": stored.get("scopes", ["https://www.googleapis.com/auth/earthengine", "https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/devstorage.full_control"]),
        }
        if stored.get("project"):
            args["quota_project_id"] = stored["project"]
        creds = credentials_lib.Credentials(**args)
        # Project: from credentials file, or from env EARTHENGINE_PROJECT. Do not use "earthengine-legacy" (no user access).
        project = stored.get("project") or os.getenv("EARTHENGINE_PROJECT") or None
        if project:
            ee.Initialize(credentials=creds, project=project)
        else:
            ee.Initialize(credentials=creds)
        ee.Number(1).getInfo()
        return True
    except Exception as e:
        _last_ee_error = str(e)
        logger.exception("Earth Engine init failed: %s", e)
        return False


def earth_engine_status() -> str:
    """Return a short status message for startup: 'ready' or why NDVI is unavailable."""
    if ee is None:
        return "earthengine-api not installed; run: pip install -r requirements.txt"
    if _ensure_ee_initialized():
        return "ready for NDVI"
    hint = _last_ee_error or "run: .venv\\Scripts\\earthengine.exe authenticate (then restart)"
    return f"not authenticated; {hint}"


def compute_mean_ndvi(
    lat: float,
    lon: float,
    buffer_m: int = 100,
    start: str = "2024-06-01",
    end: str = "2024-09-01",
    cloud_pct: int = 20,
) -> Tuple[Optional[float], dict]:
    """
    Compute mean NDVI around the given coordinate using Sentinel-2 via Google Earth Engine.

    Returns (mean_ndvi, meta_dict). When Earth Engine is not configured or the
    request fails, mean_ndvi will be None and meta_dict will explain why.
    """
    if ee is None:
        meta = {
            "source": "unavailable",
            "window": [start, end],
            "cloud_pct": cloud_pct,
            "reason": "earthengine-api is not installed; NDVI disabled.",
            "lat": lat,
            "lon": lon,
            "buffer_m": buffer_m,
        }
        return None, meta

    if not _ensure_ee_initialized():
        meta = {
            "source": "unavailable",
            "window": [start, end],
            "cloud_pct": cloud_pct,
            "reason": "Google Earth Engine is not initialized; configure credentials to enable NDVI.",
            "lat": lat,
            "lon": lon,
            "buffer_m": buffer_m,
        }
        return None, meta

    point = ee.Geometry.Point([lon, lat])
    area = point.buffer(buffer_m)

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(area)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
    )

    try:
        image = collection.median()
        ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
        stats = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=area,
            scale=10,
            maxPixels=1_000_000_000,
        )
        value = stats.get("NDVI").getInfo()
    except Exception as e:
        meta = {
            "source": "earth_engine_sentinel2",
            "window": [start, end],
            "cloud_pct": cloud_pct,
            "lat": lat,
            "lon": lon,
            "buffer_m": buffer_m,
            "error": str(e),
            "reason": "NDVI computation failed via Earth Engine.",
        }
        return None, meta

    mean_ndvi: Optional[float]
    try:
        mean_ndvi = float(value) if value is not None else None
    except (TypeError, ValueError):
        mean_ndvi = None

    thumb_url = None
    try:
        vis = {
            "min": 0,
            "max": 1,
            "palette": ["#440154", "#3b528b", "#21908d", "#5dc962", "#fde725"],
        }
        thumb_url = ndvi.clip(area).getThumbURL(
            {
                "region": area,
                "dimensions": 512,
                "min": vis["min"],
                "max": vis["max"],
                "palette": vis["palette"],
            }
        )
    except Exception:
        thumb_url = None

    meta = {
        "source": "earth_engine_sentinel2",
        "window": [start, end],
        "cloud_pct": cloud_pct,
        "lat": lat,
        "lon": lon,
        "buffer_m": buffer_m,
        "thumb_url": thumb_url,
    }
    return mean_ndvi, meta


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
