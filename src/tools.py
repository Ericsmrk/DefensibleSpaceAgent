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
        return _mock_geocode(address)

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
    seed = f"{lat}:{lon}:{buffer_m}:{start}:{end}:{cloud_pct}".encode("utf-8")
    h = int(hashlib.sha256(seed).hexdigest()[:8], 16)
    ndvi = round((h % 8500) / 10000, 4)
    return ndvi, {"source": "deterministic_mock", "window": [start, end], "cloud_pct": cloud_pct}


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

#Remove later...
def _mock_geocode(address: str) -> Tuple[float, float, dict]:
    known = {
        "17825 Woodcrest Dr, Pioneer, Ca": (38.4655752, -120.5584229),
        "48978 River Park Rd, Oakhurst, CA": (37.423609, -119.644177),
    }
    if address in known:
        lat, lon = known[address]
        return lat, lon, {"status": "OK", "source": "mock_known"}

    h = int(hashlib.md5(address.encode("utf-8")).hexdigest()[:8], 16)
    lat = round(((h % 1200000) / 10000) - 60, 6)
    lon = round((((h // 3) % 3000000) / 10000) - 150, 6)
    return lat, lon, {"status": "OK", "source": "mock_hash"}
