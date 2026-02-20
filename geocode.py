import json
import re
import time
from pathlib import Path

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "YerevanHousingIndex/1.0 (personal research project)"}
REQUEST_DELAY = 1.1  # Nominatim policy: max 1 req/sec
OVERRIDES_PATH = Path("data/geocode_overrides.json")

DISTRICT_ALIASES = {
    "Center": "Kentron",
    "Nor Norq": "Nor-Nork",
    "Nor-Norq": "Nor-Nork",
}

EU_DELEGATION_ADDRESS = "21 Frik Street, Yerevan, Armenia"
EU_DELEGATION_FALLBACK = (40.1852, 44.5136)


def geocode_address(query: str) -> tuple[float, float] | None:
    time.sleep(REQUEST_DELAY)
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "am",
    }
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"    Geocoding error for '{query}': {e}")
    return None


def load_overrides() -> dict:
    if OVERRIDES_PATH.exists():
        with open(OVERRIDES_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_overrides(overrides: dict):
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2, ensure_ascii=False)


def geocode_eu_delegation() -> tuple[float, float]:
    print("  Geocoding EU Delegation (21 Frik St)...")
    result = geocode_address(EU_DELEGATION_ADDRESS)
    if result:
        print(f"    Found: {result}")
        return result
    print(f"    Using fallback coordinates: {EU_DELEGATION_FALLBACK}")
    return EU_DELEGATION_FALLBACK


def geocode_listing(listing: dict, overrides: dict) -> dict:
    lid = str(listing["id"])

    if lid in overrides:
        lat, lng = overrides[lid]["lat"], overrides[lid]["lng"]
        listing["lat"] = lat
        listing["lng"] = lng
        listing["geocode_precision"] = "override"
        return listing

    raw_street = listing.get("street", "")
    district = listing.get("district", "")
    address_number = listing.get("parsed_address_number")

    osm_district = DISTRICT_ALIASES.get(district, district)

    street = re.sub(r"\s*\([^)]*\)\s*", " ", raw_street).strip()
    street = re.sub(r"\s+district$", "", street, flags=re.I).strip()

    queries_tried = []

    if address_number and street:
        q = f"{address_number} {street}, {osm_district}, Yerevan, Armenia"
        queries_tried.append(q)
        result = geocode_address(q)
        if result:
            listing["lat"], listing["lng"] = result
            listing["geocode_precision"] = "address"
            return listing

    if street:
        q = f"{street}, {osm_district}, Yerevan, Armenia"
        queries_tried.append(q)
        result = geocode_address(q)
        if result:
            listing["lat"], listing["lng"] = result
            listing["geocode_precision"] = "street"
            return listing

        q2 = f"{street}, Yerevan, Armenia"
        queries_tried.append(q2)
        result = geocode_address(q2)
        if result:
            listing["lat"], listing["lng"] = result
            listing["geocode_precision"] = "street"
            return listing

    if osm_district:
        q = f"{osm_district}, Yerevan, Armenia"
        queries_tried.append(q)
        result = geocode_address(q)
        if result:
            listing["lat"], listing["lng"] = result
            listing["geocode_precision"] = "district"
            return listing

    listing["lat"] = None
    listing["lng"] = None
    listing["geocode_precision"] = "failed"
    return listing


def run_geocoder(listings: list[dict]) -> tuple[list[dict], tuple[float, float]]:
    eu_coords = geocode_eu_delegation()
    overrides = load_overrides()

    to_geocode = [l for l in listings if l.get("lat") is None]
    already = len(listings) - len(to_geocode)
    if already:
        print(f"  Skipping {already} already-geocoded listings")

    failed = []
    total = len(to_geocode)
    for i, listing in enumerate(to_geocode, 1):
        lid = listing["id"]
        street = listing.get("street", "unknown")
        print(f"  [{i}/{total}] Geocoding #{lid} ({street})...")
        geocode_listing(listing, overrides)
        precision = listing.get("geocode_precision", "?")
        if listing.get("lat"):
            print(f"    -> {listing['lat']:.5f}, {listing['lng']:.5f} ({precision})")
        else:
            print(f"    -> FAILED")
            failed.append(listing)

    new_overrides = {}
    for listing in failed:
        lid = str(listing["id"])
        if lid not in overrides:
            new_overrides[lid] = {
                "lat": None,
                "lng": None,
                "street": listing.get("street", ""),
                "note": "needs manual geocoding",
            }

    if new_overrides:
        merged = {**overrides, **new_overrides}
        save_overrides(merged)
        print(f"\n  {len(new_overrides)} listings need manual geocoding.")
        print(f"  Edit {OVERRIDES_PATH} to add lat/lng values, then re-run.")

    success_count = sum(1 for l in listings if l.get("lat") is not None)
    print(f"\n  Geocoded: {success_count}/{total} ({total - success_count} failed)")

    return listings, eu_coords


if __name__ == "__main__":
    data_path = Path("data/listings.json")
    with open(data_path, encoding="utf-8") as f:
        listings = json.load(f)
    run_geocoder(listings)
