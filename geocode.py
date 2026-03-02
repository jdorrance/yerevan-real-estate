import json
import re
import time
from pathlib import Path

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "YerevanHousingIndex/1.0 (personal research project)"}
REQUEST_DELAY = 1.1  # Nominatim policy: max 1 req/sec
OVERRIDES_PATH = Path("data/geocode_overrides.json")
DISTRICT_BBOX_CACHE_PATH = Path("data/district_bbox.json")

# Allow a small amount of wiggle room for district boundaries / bbox approximations.
# (From the attached plan: ~300m tolerance in degrees.)
BBOX_BUFFER = 0.003

_DISTRICT_BBOX_MEM_CACHE: dict[str, tuple[float, float, float, float]] | None = None

DISTRICT_ALIASES = {
    "Center": "Kentron",
    "Nor Norq": "Nor-Nork",
    "Nor-Norq": "Nor-Nork",
    "Norq Marash": "Nork-Marash",
    "Achapnyak": "Ajapnyak",
    "Vahagni district": "Vahagni",
}

EU_DELEGATION_ADDRESS = "21 Frik Street, Yerevan, Armenia"
EU_DELEGATION_FALLBACK = (40.1852, 44.5136)


def _nominatim_search(params: dict) -> list[dict]:
    time.sleep(REQUEST_DELAY)
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        q = params.get("q") or params.get("street") or "?"
        print(f"    Geocoding error for '{q}': {e}")
        return []


def geocode_address(
    query: str,
    *,
    viewbox: tuple[float, float, float, float] | None = None,
    bounded: bool = False,
) -> tuple[float, float] | None:
    """
    Geocode a free-text query via Nominatim.

    If viewbox is provided, it is interpreted as (south, north, west, east) and passed to Nominatim
    as a bounded search (when bounded=True).
    """
    params: dict = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "am",
    }
    if viewbox is not None:
        south, north, west, east = viewbox
        # Nominatim expects viewbox as: left,top,right,bottom (lon/lat).
        params["viewbox"] = f"{west},{north},{east},{south}"
        if bounded:
            params["bounded"] = 1

    results = _nominatim_search(params)
    if results:
        try:
            return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception:
            return None
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


def _load_district_bbox_cache() -> dict[str, tuple[float, float, float, float]]:
    if DISTRICT_BBOX_CACHE_PATH.exists():
        try:
            with open(DISTRICT_BBOX_CACHE_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            out: dict[str, tuple[float, float, float, float]] = {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if not isinstance(k, str) or not isinstance(v, list) or len(v) != 4:
                        continue
                    try:
                        south, north, west, east = (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
                    except Exception:
                        continue
                    out[k] = (south, north, west, east)
            return out
        except Exception:
            return {}
    return {}


def _save_district_bbox_cache(cache: dict[str, tuple[float, float, float, float]]):
    DISTRICT_BBOX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serializable = {k: [v[0], v[1], v[2], v[3]] for k, v in cache.items()}
    with open(DISTRICT_BBOX_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)


def _fetch_district_bbox(osm_district: str) -> tuple[float, float, float, float] | None:
    """
    Ask Nominatim for a bounding box for the given district query.
    Returns bbox as (south, north, west, east) or None if unavailable.
    """
    q = f"{osm_district}, Yerevan, Armenia"
    params: dict = {
        "q": q,
        "format": "json",
        "limit": 1,
        "countrycodes": "am",
        "addressdetails": 1,
    }
    results = _nominatim_search(params)
    if not results:
        return None
    bb = results[0].get("boundingbox")
    if not isinstance(bb, list) or len(bb) != 4:
        return None
    try:
        south = float(bb[0])
        north = float(bb[1])
        west = float(bb[2])
        east = float(bb[3])
        return (south, north, west, east)
    except Exception:
        return None


def get_district_bbox(osm_district: str) -> tuple[float, float, float, float] | None:
    """
    Return cached district bbox, fetching it once from Nominatim if needed.
    """
    global _DISTRICT_BBOX_MEM_CACHE
    osm_district = (osm_district or "").strip()
    if not osm_district:
        return None
    if _DISTRICT_BBOX_MEM_CACHE is None:
        _DISTRICT_BBOX_MEM_CACHE = _load_district_bbox_cache()
    cache = _DISTRICT_BBOX_MEM_CACHE
    if osm_district in cache:
        return cache[osm_district]
    bbox = _fetch_district_bbox(osm_district)
    if bbox is None:
        return None
    cache[osm_district] = bbox
    _save_district_bbox_cache(cache)
    return bbox


def _expand_bbox(
    bbox: tuple[float, float, float, float], buffer_deg: float = BBOX_BUFFER
) -> tuple[float, float, float, float]:
    south, north, west, east = bbox
    return (south - buffer_deg, north + buffer_deg, west - buffer_deg, east + buffer_deg)


def in_district_bbox(lat: float, lng: float, district: str) -> bool | None:
    """
    Returns:
      - True/False if the district bbox is known
      - None if no bbox could be determined (so callers can choose a safe fallback)
    """
    if lat is None or lng is None:
        return None
    osm_district = DISTRICT_ALIASES.get(district or "", district or "").strip()
    if not osm_district:
        return None
    bbox = get_district_bbox(osm_district)
    if bbox is None:
        return None
    south, north, west, east = _expand_bbox(bbox)
    return (south <= lat <= north) and (west <= lng <= east)


STREET_ALIASES = {
    # From the attached plan.
    "g 1 dis.": "G1 microdistrict",
    "vahakni district": "Vahagni district",
    "ashtarak hightway": "Ashtarak highway",
}


def _normalize_street(raw_street: str) -> str:
    s = raw_street or ""
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s).strip()
    s = re.sub(r"\s+district$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s).strip()
    aliased = STREET_ALIASES.get(s.lower())
    return aliased if aliased else s


def geocode_eu_delegation() -> tuple[float, float]:
    print("  Geocoding EU Delegation (21 Frik St)...")
    result = geocode_address(EU_DELEGATION_ADDRESS)
    if result:
        print(f"    Found: {result}")
        return result
    print(f"    Using fallback coordinates: {EU_DELEGATION_FALLBACK}")
    return EU_DELEGATION_FALLBACK


def _try_geocode(
    query: str,
    district: str,
    viewbox: tuple[float, float, float, float] | None,
) -> tuple[float, float] | None:
    """
    Try geocoding with viewbox bias. If the unbounded result is clearly in the
    wrong district, retry once with bounded=True. Return the best result or None.
    """
    result = geocode_address(query, viewbox=viewbox)
    if result is None:
        return None

    ok = in_district_bbox(result[0], result[1], district)
    if ok is not False:
        return result

    # First result landed outside the district. One bounded retry.
    if viewbox is not None:
        bounded_result = geocode_address(query, viewbox=viewbox, bounded=True)
        if bounded_result is not None:
            ok2 = in_district_bbox(bounded_result[0], bounded_result[1], district)
            if ok2 is not False:
                return bounded_result

    # Fall through — caller will try the next query tier.
    return None


def geocode_listing(listing: dict, overrides: dict) -> dict:
    lid = str(listing["id"])

    # Some sources provide their own (approximate) coordinates.
    if listing.get("geocode_precision") == "source_approx" and listing.get("lat") is not None and listing.get("lng") is not None:
        return listing

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
    street = _normalize_street(raw_street)

    # Non-bounded viewbox preference — nudges Nominatim toward the correct area
    # without hard-rejecting results outside the rectangle.
    district_bbox = get_district_bbox(osm_district) if osm_district else None
    vbox = _expand_bbox(district_bbox) if district_bbox else None

    # --- tier 1: full address ---
    if address_number and street:
        q = f"{address_number} {street}, {osm_district}, Yerevan, Armenia"
        result = _try_geocode(q, district, vbox)
        if result:
            listing["lat"], listing["lng"] = result
            listing["geocode_precision"] = "address"
            return listing

    # --- tier 2: street + district ---
    if street:
        q = f"{street}, {osm_district}, Yerevan, Armenia"
        result = _try_geocode(q, district, vbox)
        if result:
            listing["lat"], listing["lng"] = result
            listing["geocode_precision"] = "street"
            return listing

    # --- tier 3: street only (no district qualifier) ---
    if street:
        q = f"{street}, Yerevan, Armenia"
        result = _try_geocode(q, district, vbox)
        if result:
            listing["lat"], listing["lng"] = result
            listing["geocode_precision"] = "street"
            return listing

    # --- tier 4: district centroid ---
    if osm_district:
        q = f"{osm_district}, Yerevan, Armenia"
        result = geocode_address(q, viewbox=vbox)
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
