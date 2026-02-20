import json
import time
from pathlib import Path

import requests


OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]
HEADERS = {"User-Agent": "YerevanHousingIndex/1.0 (personal research project)"}

# Rough bounding box around Yerevan (south, west, north, east)
YEREVAN_BBOX = (40.10, 44.40, 40.30, 44.65)
REQUEST_DELAY = 1.1


def _post_overpass(query: str) -> dict:
    last_err: Exception | None = None
    for url in OVERPASS_URLS:
        time.sleep(REQUEST_DELAY)
        try:
            resp = requests.post(url, data={"data": query}, headers=HEADERS, timeout=(10, 40))
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


def fetch_greens_overpass(*, bbox: tuple[float, float, float, float] = YEREVAN_BBOX, cache_path: Path) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    south, west, north, east = bbox
    # nwr = nodes + ways + relations. We request center for non-node elements so we can still render something.
    query = (
        "[out:json][timeout:60];("
        f"nwr[\"leisure\"=\"park\"]({south},{west},{north},{east});"
        f"nwr[\"leisure\"=\"garden\"]({south},{west},{north},{east});"
        f"nwr[\"leisure\"=\"dog_park\"]({south},{west},{north},{east});"
        ");out center geom;"
    )
    data = _post_overpass(query)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def overpass_to_geojson(data: dict) -> dict:
    features: list[dict] = []
    for e in data.get("elements", []):
        etype = e.get("type")
        tags = e.get("tags") or {}
        leisure = tags.get("leisure")
        if leisure not in {"park", "garden", "dog_park"}:
            continue

        name = tags.get("name") or tags.get("name:en") or ""

        geom = e.get("geometry")
        if etype == "node":
            lat = e.get("lat")
            lon = e.get("lon")
            if lat is None or lon is None:
                continue
            geometry = {"type": "Point", "coordinates": [float(lon), float(lat)]}
        elif isinstance(geom, list) and len(geom) >= 2:
            coords = [[float(p["lon"]), float(p["lat"])] for p in geom]
            # closed way -> polygon
            if coords[0] == coords[-1] and len(coords) >= 4:
                geometry = {"type": "Polygon", "coordinates": [coords]}
            else:
                geometry = {"type": "LineString", "coordinates": coords}
        else:
            center = e.get("center")
            if not center:
                continue
            geometry = {"type": "Point", "coordinates": [float(center["lon"]), float(center["lat"])]}

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": leisure,
                    "name": name,
                    "osm_type": etype,
                    "osm_id": e.get("id"),
                },
                "geometry": geometry,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def write_greens_geojson(*, out_path: Path, force: bool = False) -> bool:
    """
    Writes a GeoJSON FeatureCollection to out_path. Returns True if written.

    Cached Overpass response: data/raw/overpass_greens.json (gitignored).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not force:
        return False

    cache = Path("data/raw/overpass_greens.json")
    data = fetch_greens_overpass(cache_path=cache)
    geojson = overpass_to_geojson(data)
    out_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    return True

