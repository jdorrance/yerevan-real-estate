import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]
HEADERS = {"User-Agent": "YerevanHousingIndex/1.0 (personal research project)"}

# Rough bounding box around Yerevan (south, west, north, east)
YEREVAN_BBOX = (40.10, 44.40, 40.30, 44.65)

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Be polite to Overpass. Cache makes this mostly a one-time cost.
REQUEST_DELAY = 1.1


def _post_overpass(query: str) -> dict:
    """
    Execute an Overpass query with basic retries and endpoint fallback.
    """
    # Overpass nodes can be rate-limited or temporarily overloaded. We try a few instances.
    # Keep delays bounded; caching means we only pay this once per street.
    last_err: Exception | None = None

    for url in OVERPASS_URLS:
        time.sleep(REQUEST_DELAY)
        try:
            resp = requests.post(url, data={"data": query}, headers=HEADERS, timeout=(10, 35))
            # Treat 429/5xx as retryable by falling back to another instance.
            if resp.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests", response=resp)
            if resp.status_code in {502, 503, 504}:
                raise requests.HTTPError(f"{resp.status_code} Server Error", response=resp)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            # Short backoff before trying the next instance.
            time.sleep(2.0)

    if last_err:
        raise last_err
    raise RuntimeError("Overpass request failed (unknown error)")


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "street"


def _stable_u32(value: str) -> int:
    h = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _polyline_length_m(line: list[tuple[float, float]]) -> float:
    if len(line) < 2:
        return 0.0
    total = 0.0
    for (a_lat, a_lon), (b_lat, b_lon) in zip(line, line[1:]):
        total += _haversine_m(a_lat, a_lon, b_lat, b_lon)
    return total


def _nearest_vertex_dist_m(point: tuple[float, float], line: list[tuple[float, float]]) -> float:
    lat, lon = point
    best = float("inf")
    for v_lat, v_lon in line:
        d = _haversine_m(lat, lon, v_lat, v_lon)
        if d < best:
            best = d
    return best


def _normalize_street_for_query(street: str) -> str:
    s = re.sub(r"\s*\([^)]*\)\s*", " ", street).strip()
    s = re.sub(r"\s+district$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+dead end$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+alley$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+hightway$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+highway$", "", s, flags=re.I).strip()
    # common abbreviations
    s = re.sub(r"\bAve\b\.?", "Avenue", s)
    s = re.sub(r"\bav\b\.?", "Avenue", s, flags=re.I)
    s = re.sub(r"\bSt\b\.?", "Street", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_area_like(street: str) -> bool:
    s = street.lower()
    return "district" in s


@dataclass(frozen=True)
class StreetGeometry:
    # A street may be represented by multiple disconnected ways.
    lines: list[list[tuple[float, float]]]

    @property
    def total_length_m(self) -> float:
        return sum(_polyline_length_m(line) for line in self.lines)


def fetch_street_geometry(
    street_name: str,
    centroid: tuple[float, float],
    bbox: tuple[float, float, float, float] = YEREVAN_BBOX,
) -> Optional[StreetGeometry]:
    """
    Fetch road geometry for `street_name` from Overpass. Returns a set of polylines (ways).
    Uses a cache under data/raw/overpass_<slug>.json.
    """
    normalized = _normalize_street_for_query(street_name)
    cache_path = RAW_DIR / f"overpass_{_slug(normalized)}.json"

    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        south, west, north, east = bbox
        # Use a loose regex to tolerate Street/street naming differences and minor variations.
        # Overpass regex flags are provided after the pattern (e.g. ~"foo",i).
        pattern = re.escape(normalized).replace('"', r"\"")
        query = (
            "[out:json][timeout:60];"
            f"(way[\"highway\"][\"name:en\"~\"{pattern}\",i]({south},{west},{north},{east});"
            f"way[\"highway\"][\"name\"~\"{pattern}\",i]({south},{west},{north},{east}););"
            "out geom;"
        )
        data = _post_overpass(query)
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    elems = data.get("elements", [])
    if not elems:
        return None

    # Extract candidate polylines
    candidates: list[list[tuple[float, float]]] = []
    for e in elems:
        if e.get("type") != "way":
            continue
        geom = e.get("geometry") or []
        if len(geom) < 2:
            continue
        line = [(float(p["lat"]), float(p["lon"])) for p in geom]
        candidates.append(line)

    if not candidates:
        return None

    # Keep only ways plausibly near the original centroid (helps when regex matches too much).
    # Choose ways within 2km of the centroid by nearest vertex distance.
    max_keep_dist_m = 2000.0
    centroid_latlng = centroid
    near = [(line, _nearest_vertex_dist_m(centroid_latlng, line)) for line in candidates]
    near.sort(key=lambda x: x[1])
    near = [(line, d) for (line, d) in near if d <= max_keep_dist_m]
    if not near:
        # If nothing is within 2km, fall back to best few matches.
        near = [(line, d) for (line, d) in [(line, _nearest_vertex_dist_m(centroid_latlng, line)) for line in candidates]]
        near.sort(key=lambda x: x[1])
        near = near[:5]

    lines = [line for (line, _d) in near]
    geom = StreetGeometry(lines=lines)
    if geom.total_length_m <= 50:
        return None
    return geom


def interpolate_points_along_geometry(geom: StreetGeometry, n: int) -> list[tuple[float, float]]:
    """
    Evenly distribute N points across the combined length of the street geometry.
    """
    if n <= 0:
        return []

    lengths = [max(_polyline_length_m(line), 0.0) for line in geom.lines]
    total = sum(lengths)
    if total <= 0:
        return []

    # Build cumulative table of (line_index, cumulative_length)
    cum = []
    running = 0.0
    for i, ln in enumerate(lengths):
        running += ln
        cum.append((i, running))

    def point_at_distance(line: list[tuple[float, float]], dist_m: float) -> tuple[float, float]:
        if dist_m <= 0:
            return line[0]
        remaining = dist_m
        for (a_lat, a_lon), (b_lat, b_lon) in zip(line, line[1:]):
            seg = _haversine_m(a_lat, a_lon, b_lat, b_lon)
            if seg <= 0:
                continue
            if remaining <= seg:
                t = remaining / seg
                return (a_lat + (b_lat - a_lat) * t, a_lon + (b_lon - a_lon) * t)
            remaining -= seg
        return line[-1]

    out: list[tuple[float, float]] = []
    for i in range(n):
        target = total * ((i + 0.5) / n)
        # Find which polyline this target falls on
        prev_c = 0.0
        chosen_idx = 0
        for idx, c in cum:
            if target <= c:
                chosen_idx = idx
                break
            prev_c = c
        local = target - prev_c
        out.append(point_at_distance(geom.lines[chosen_idx], local))
    return out


def deterministic_jitter(
    center: tuple[float, float],
    listing_id: int,
    *,
    radius_m: float,
) -> tuple[float, float]:
    """
    Deterministically place a point within radius_m of center.
    """
    lat, lon = center
    u = _stable_u32(str(listing_id))
    # angle in [0, 2pi)
    angle = (u % 3600) / 3600.0 * 2.0 * math.pi
    # radius in [0, radius_m), with sqrt for uniform area
    u2 = _stable_u32(f"{listing_id}:r")
    r = radius_m * math.sqrt((u2 % 10_000) / 10_000.0)

    dlat = (r * math.cos(angle)) / 111_111.0
    denom = 111_111.0 * max(math.cos(math.radians(lat)), 1e-6)
    dlon = (r * math.sin(angle)) / denom
    return (lat + dlat, lon + dlon)


def run_spread(listings: list[dict]) -> list[dict]:
    """
    Spread stacked listings.

    - For street-precision listings with identical coordinates (per-street), fetch street geometry and distribute them
      along the street line(s).
    - For area-like streets (\"... district\") and district-precision listings, apply deterministic jitter around centroid.
    """
    # Group street-precision listings by street label.
    by_street: dict[str, list[dict]] = {}
    district_level: list[dict] = []

    for l in listings:
        lat = l.get("lat")
        lng = l.get("lng")
        if lat is None or lng is None:
            continue
        precision = (l.get("geocode_precision") or "").lower()
        street = (l.get("street") or "").strip()
        if street and precision in {"street", "street_jitter", "street_spread"}:
            by_street.setdefault(street, []).append(l)
        elif precision == "district":
            district_level.append(l)

    moved = 0
    spread_streets = 0
    jittered = 0

    # Spread street-level listings across the street geometry.
    # We do this whenever a street has 2+ listings; relying purely on "identical coord" breaks
    # once jitter has already been applied, and the goal is to avoid piles for street-only data.
    streets = [(street, items) for street, items in by_street.items() if len(items) > 1]
    streets.sort(key=lambda x: (-len(x[1]), x[0].lower()))

    total_streets = len(streets)
    for idx, (street, items) in enumerate(streets, 1):
        if len(items) <= 1:
            continue

        print(f"  Spread [{idx}/{total_streets}] {street} ({len(items)} listings)...")

        # If it's actually an area/neighborhood name, jitter instead of line-spreading.
        if _is_area_like(street):
            # Keep as jittered (or apply jitter deterministically if still "street")
            center = (float(items[0]["lat"]), float(items[0]["lng"]))
            radius = 300.0
            for l in items:
                lid = int(l["id"])
                lat2, lng2 = deterministic_jitter(center, lid, radius_m=radius)
                l["lat"], l["lng"] = lat2, lng2
                l["geocode_precision"] = "district_jitter"
                moved += 1
                jittered += 1
            continue

        # Try to fetch geometry once per street.
        ref_center = (
            sum(float(l["lat"]) for l in items) / len(items),
            sum(float(l["lng"]) for l in items) / len(items),
        )
        geom = None
        try:
            geom = fetch_street_geometry(street, centroid=ref_center)
        except Exception as e:
            print(f"  Spread: Overpass error for '{street}': {e}")
            geom = None

        if not geom:
            # Small jitter fallback (street-level but no geometry)
            center = ref_center
            radius = 80.0
            for l in items:
                lid = int(l["id"])
                lat2, lng2 = deterministic_jitter(center, lid, radius_m=radius)
                l["lat"], l["lng"] = lat2, lng2
                l["geocode_precision"] = "street_jitter"
                moved += 1
                jittered += 1
            continue

        spread_streets += 1
        items_sorted = sorted(items, key=lambda x: int(x["id"]))
        pts = interpolate_points_along_geometry(geom, len(items_sorted))
        if len(pts) == len(items_sorted):
            for l, (lat2, lng2) in zip(items_sorted, pts):
                l["lat"], l["lng"] = lat2, lng2
                l["geocode_precision"] = "street_spread"
                moved += 1

    # Jitter district-level stacks (only when stacked at same coordinate)
    coord_groups_d: dict[tuple[float, float], list[dict]] = {}
    for l in district_level:
        coord_groups_d.setdefault((float(l["lat"]), float(l["lng"])), []).append(l)
    for group in coord_groups_d.values():
        if len(group) <= 1:
            continue
        center = (float(group[0]["lat"]), float(group[0]["lng"]))
        radius = 400.0
        for l in group:
            lid = int(l["id"])
            lat2, lng2 = deterministic_jitter(center, lid, radius_m=radius)
            l["lat"], l["lng"] = lat2, lng2
            l["geocode_precision"] = "district_jitter"
            moved += 1
            jittered += 1

    print(f"  Spread: moved {moved} listings ({spread_streets} streets spread, {jittered} jittered)")
    return listings

