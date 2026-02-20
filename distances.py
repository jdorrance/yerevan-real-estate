import math
import time

import requests

OSRM_BASE = "http://router.project-osrm.org/route/v1"
REQUEST_DELAY = 0.5


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def osrm_route(
    lat1: float, lon1: float, lat2: float, lon2: float, profile: str = "driving"
) -> tuple[float, float] | None:
    """Query OSRM for route. Returns (duration_minutes, distance_km) or None."""
    url = f"{OSRM_BASE}/{profile}/{lon1},{lat1};{lon2},{lat2}"
    params = {"overview": "false"}
    try:
        time.sleep(REQUEST_DELAY)
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == "Ok" and data.get("routes"):
            route = data["routes"][0]
            duration_min = route["duration"] / 60.0
            distance_km = route["distance"] / 1000.0
            return round(duration_min, 1), round(distance_km, 2)
    except Exception as e:
        print(f"    OSRM error ({profile}): {e}")
    return None


def compute_distances(
    listings: list[dict], eu_lat: float, eu_lng: float
) -> list[dict]:
    total = len(listings)
    for i, listing in enumerate(listings, 1):
        lat = listing.get("lat")
        lng = listing.get("lng")

        if lat is None or lng is None:
            listing["walk_mins_to_eu"] = None
            listing["walk_km_to_eu"] = None
            listing["drive_mins_to_eu"] = None
            listing["drive_km_to_eu"] = None
            listing["straight_line_km_to_eu"] = None
            continue

        street = listing.get("street", "?")
        print(f"  [{i}/{total}] Distance for #{listing['id']} ({street})...")

        listing["straight_line_km_to_eu"] = round(
            haversine_km(lat, lng, eu_lat, eu_lng), 2
        )

        driving = osrm_route(lat, lng, eu_lat, eu_lng, "driving")
        if driving:
            listing["drive_mins_to_eu"], listing["drive_km_to_eu"] = driving
            print(f"    Drive: {driving[0]} min, {driving[1]} km")
        else:
            listing["drive_mins_to_eu"] = None
            listing["drive_km_to_eu"] = None

        walking = osrm_route(lat, lng, eu_lat, eu_lng, "walking")
        if walking:
            listing["walk_mins_to_eu"], listing["walk_km_to_eu"] = walking
            print(f"    Walk: {walking[0]} min, {walking[1]} km")
        else:
            listing["walk_mins_to_eu"] = None
            listing["walk_km_to_eu"] = None

    return listings
