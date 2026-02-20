import heapq
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import requests
import shapely
from shapely.geometry import MultiPoint, mapping


ORS_ISOCHRONES_URL = "https://api.openrouteservice.org/v2/isochrones/foot-walking"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]


WALK_SPEED_MPS = 1.35  # ~4.9 km/h
OVERPASS_DELAY_S = 1.1


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_walking_isochrones_geojson_ors(
    *,
    api_key: str,
    center_lat: float,
    center_lng: float,
    minutes: Iterable[int] = (15, 30, 45, 60),
) -> dict:
    ranges_s = [int(m) * 60 for m in minutes]
    body = {
        "locations": [[float(center_lng), float(center_lat)]],
        "range": ranges_s,
        "range_type": "time",
        "smoothing": 0.7,
    }
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/geo+json",
        "User-Agent": "YerevanHousingIndex/1.0 (personal research project)",
    }
    resp = requests.post(ORS_ISOCHRONES_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post_overpass(query: str) -> dict:
    last_err: Exception | None = None
    for url in OVERPASS_URLS:
        time.sleep(OVERPASS_DELAY_S)
        try:
            resp = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": "YerevanHousingIndex/1.0 (personal research project)"},
                timeout=(10, 40),
            )
            if resp.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests", response=resp)
            if resp.status_code in {502, 503, 504}:
                raise requests.HTTPError(f"{resp.status_code} Server Error", response=resp)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            time.sleep(2.0)
    if last_err:
        raise last_err
    raise RuntimeError("Overpass request failed")


def _bbox_for_time(center_lat: float, center_lng: float, max_minutes: int) -> tuple[float, float, float, float]:
    # crude bound: max distance = time * speed; add 20% and convert to degrees
    max_m = max_minutes * 60 * WALK_SPEED_MPS * 1.2
    dlat = max_m / 111_111.0
    import math

    dlon = max_m / (111_111.0 * max(math.cos(math.radians(center_lat)), 1e-6))
    return (center_lat - dlat, center_lng - dlon, center_lat + dlat, center_lng + dlon)


def fetch_walk_network_overpass(
    *,
    center_lat: float,
    center_lng: float,
    max_minutes: int,
    cache_path: Path,
) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    print("  Isochrones: fetching walk network from Overpass...")
    south, west, north, east = _bbox_for_time(center_lat, center_lng, max_minutes)

    # Keep it broad: include most roads/paths, exclude major motorways/trunks.
    query = (
        "[out:json][timeout:60];"
        f"way[highway][area!=yes]({south},{west},{north},{east})"
        '["highway"!~"motorway|motorway_link|trunk|trunk_link"]'
        '["access"!="private"]'
        ";out geom;"
    )
    data = _post_overpass(query)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def build_graph_from_overpass(data: dict) -> tuple[dict[tuple[float, float], list[tuple[tuple[float, float], float]]], set[tuple[float, float]]]:
    """
    Build an undirected adjacency list: node -> [(neighbor, seconds), ...]
    Nodes are lat/lng tuples rounded to 6 decimals to merge near-identical points.
    """
    adj: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = defaultdict(list)
    nodes: set[tuple[float, float]] = set()

    def norm(lat: float, lng: float) -> tuple[float, float]:
        return (round(lat, 6), round(lng, 6))

    for e in data.get("elements", []):
        if e.get("type") != "way":
            continue
        geom = e.get("geometry") or []
        if len(geom) < 2:
            continue
        pts = [norm(float(p["lat"]), float(p["lon"])) for p in geom]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            dist = _haversine_m(a[0], a[1], b[0], b[1])
            secs = dist / WALK_SPEED_MPS
            adj[a].append((b, secs))
            adj[b].append((a, secs))
            nodes.add(a)
            nodes.add(b)

    return adj, nodes


def nearest_node(nodes: set[tuple[float, float]], lat: float, lng: float) -> tuple[float, float]:
    best = None
    best_d = float("inf")
    for nlat, nlng in nodes:
        d = _haversine_m(lat, lng, nlat, nlng)
        if d < best_d:
            best_d = d
            best = (nlat, nlng)
    if best is None:
        raise RuntimeError("No nodes in walk network")
    return best


def dijkstra_times(
    adj: dict[tuple[float, float], list[tuple[tuple[float, float], float]]],
    source: tuple[float, float],
    max_time_s: float,
) -> dict[tuple[float, float], float]:
    dist: dict[tuple[float, float], float] = {source: 0.0}
    pq: list[tuple[float, tuple[float, float]]] = [(0.0, source)]
    while pq:
        t, u = heapq.heappop(pq)
        if t != dist.get(u):
            continue
        if t > max_time_s:
            continue
        for v, w in adj.get(u, []):
            nt = t + w
            if nt > max_time_s:
                continue
            if nt < dist.get(v, float("inf")):
                dist[v] = nt
                heapq.heappush(pq, (nt, v))
    return dist


def polygon_for_budget(
    *,
    adj: dict[tuple[float, float], list[tuple[tuple[float, float], float]]],
    times: dict[tuple[float, float], float],
    budget_s: int,
    buffer_m: float = 70.0,
) -> dict:
    """Approximate isochrone polygon using concave hull of reachable nodes."""
    pts = [(n[1], n[0]) for n, t in times.items() if t <= budget_s]  # (lng,lat)
    if len(pts) < 3:
        return {"type": "Feature", "properties": {"value": budget_s}, "geometry": None}

    mp = MultiPoint(pts)
    # ratio in [0,1]; higher -> closer to convex hull, lower -> more concave.
    poly = shapely.concave_hull(mp, ratio=0.35, allow_holes=False)
    # If concave hull degenerates (rare), fall back to convex hull.
    if poly.geom_type not in {"Polygon", "MultiPolygon"}:
        poly = mp.convex_hull
    # small smoothing buffer (convert meters to degrees-ish)
    poly = poly.buffer(buffer_m / 111_111.0).buffer(0)

    return {
        "type": "Feature",
        "properties": {"value": budget_s},
        "geometry": mapping(poly),
    }


def generate_walk_isochrones_geojson_overpass(
    *,
    center_lat: float,
    center_lng: float,
    minutes: Iterable[int],
    cache_path: Path,
) -> dict:
    minutes_list = sorted({int(m) for m in minutes})
    max_minutes = max(minutes_list)

    data = fetch_walk_network_overpass(
        center_lat=center_lat,
        center_lng=center_lng,
        max_minutes=max_minutes,
        cache_path=cache_path,
    )
    print("  Isochrones: building graph...")
    adj, nodes = build_graph_from_overpass(data)
    print(f"  Isochrones: graph nodes={len(nodes):,}")
    src = nearest_node(nodes, center_lat, center_lng)
    print("  Isochrones: running Dijkstra...")
    times = dijkstra_times(adj, src, max_minutes * 60)
    print(f"  Isochrones: reachable nodes={len(times):,} within {max_minutes} min")

    features = []
    for m in minutes_list:
        print(f"  Isochrones: polygon {m} min...")
        features.append(polygon_for_budget(adj=adj, times=times, budget_s=m * 60))

    return {"type": "FeatureCollection", "features": features}


def maybe_write_isochrones(
    *,
    center_lat: float,
    center_lng: float,
    out_path: Path,
    minutes: Iterable[int] = (15, 30, 45, 60),
    force: bool = False,
) -> bool:
    """
    Write isochrones GeoJSON to out_path.

    - If ORS_API_KEY is set: use OpenRouteService.
    - Else: generate an approximate isochrone from OSM walking network via Overpass.

    If out_path already exists and force=False, does nothing (keeps committed file stable).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not force and not os.environ.get("ORS_API_KEY"):
        return False

    api_key = os.environ.get("ORS_API_KEY", "").strip()
    if api_key:
        geojson = fetch_walking_isochrones_geojson_ors(
            api_key=api_key, center_lat=center_lat, center_lng=center_lng, minutes=minutes
        )
    else:
        cache = Path("data/raw/overpass_walk_network.json")
        geojson = generate_walk_isochrones_geojson_overpass(
            center_lat=center_lat, center_lng=center_lng, minutes=minutes, cache_path=cache
        )

    out_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    return True

