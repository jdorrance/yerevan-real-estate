#!/usr/bin/env python3
"""
Resolve exact street addresses for favorited listings.

Combines multiple signals:
  1. Nominatim reverse geocoding at the listing's coordinates
  2. Cross-reference with Kentron (real-estate.am) listings that have precise Yandex coords
     (reverse-geocode the Kentron coords for a much better result)
  3. Listing description text for address clues
  4. AI vision on exterior photos (first 1-2) as a last resort

Writes resolved_address, resolved_address_confidence, and resolved_address_source
back into data/listings.json for each favorite.

Usage:
  python resolve_addresses.py                   # run on all favorites
  python resolve_addresses.py --ids 10576,11038 # specific IDs only
  python resolve_addresses.py --dry-run         # print without writing
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests

NOMINATIM_DELAY = 1.1
HEADERS_NOM = {"User-Agent": "YerevanRentals/1.0"}


def reverse_geocode(lat: float, lng: float) -> dict:
    time.sleep(NOMINATIM_DELAY)
    resp = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "format": "json",
            "lat": lat,
            "lon": lng,
            "zoom": 19,
            "addressdetails": 1,
            "accept-language": "en",
        },
        headers=HEADERS_NOM,
        timeout=10,
    )
    data = resp.json()
    addr = data.get("address", {})
    return {
        "road": addr.get("road", ""),
        "house_number": addr.get("house_number", ""),
        "display_name": data.get("display_name", ""),
        "suburb": addr.get("suburb", ""),
        "postcode": addr.get("postcode", ""),
    }


_ABBREVIATIONS = {
    "n": "nairi",
    "v": "vahram",
    "a": "armenak",
    "h": "hovhannes",
    "m": "movses",
}


def _normalize_street(s: str) -> str:
    """Normalize street name for fuzzy matching."""
    s = s.lower()
    for suffix in [" street", " st", " ave", " avenue", " alley", " dead end", " blind allay"]:
        s = s.replace(suffix, "")
    s = s.replace(".", "").replace("-", " ").replace(",", " ").strip()
    # Expand single-letter abbreviations
    parts = s.split()
    expanded = []
    for p in parts:
        if len(p) <= 2 and p in _ABBREVIATIONS:
            expanded.append(_ABBREVIATIONS[p])
        else:
            expanded.append(p)
    return " ".join(expanded)


def _streets_match(listing_street: str, reverse_road: str) -> bool:
    a = _normalize_street(listing_street)
    b = _normalize_street(reverse_road)
    if not a or not b:
        return False
    # Direct substring
    if a in b or b in a:
        return True
    # Token overlap: if at least one significant word overlaps
    a_words = set(w for w in a.split() if len(w) > 2)
    b_words = set(w for w in b.split() if len(w) > 2)
    overlap = a_words & b_words
    return len(overlap) > 0


def _parse_description_for_number(desc: str, street: str) -> str | None:
    """Try to extract a house number from the description."""
    if not desc:
        return None
    patterns = [
        re.compile(rf"(\d+)\s*{re.escape(_normalize_street(street))}", re.I),
        re.compile(rf"{re.escape(_normalize_street(street))}\s*(\d+)", re.I),
        re.compile(r"(?:house|building|at|number|N\.?)\s*#?\s*(\d+)", re.I),
        re.compile(r"(\d+)\s*(?:,\s*)?{0}".format(re.escape(street.split()[0])), re.I) if street else None,
    ]
    for pat in patterns:
        if pat is None:
            continue
        m = pat.search(desc)
        if m:
            return m.group(1)
    return None


def resolve_listing(
    listing: dict,
    kentron_by_street: dict[str, list[dict]],
    rev_cache: dict[int, dict],
    ai_client=None,
) -> dict:
    """
    Resolve the address for one listing. Returns dict with
    address, confidence, source fields.
    """
    lid = listing["id"]
    street = listing.get("street") or ""
    district = (listing.get("district") or "").lower().strip()
    lat, lng = listing.get("lat"), listing.get("lng")
    desc = (listing.get("description") or "").strip()

    candidates: list[dict] = []

    # --- Signal 1: Cross-reference with Kentron (precise Yandex coords) ---
    street_key = _normalize_street(street)
    kentron_matches = kentron_by_street.get(street_key, [])
    for km in kentron_matches:
        if km.get("geocode_precision") != "source_map":
            continue
        km_lat, km_lng = km.get("lat"), km.get("lng")
        if not km_lat or not km_lng:
            continue
        cache_key = f"kentron_{km['id']}"
        if cache_key not in rev_cache:
            print(f"  Reverse-geocoding Kentron #{km['id']} coords...")
            rev_cache[cache_key] = reverse_geocode(km_lat, km_lng)
        rev = rev_cache[cache_key]
        if rev.get("house_number") and _streets_match(street, rev.get("road", "")):
            candidates.append({
                "address": f"{rev['house_number']} {rev['road']}",
                "confidence": "HIGH",
                "source": f"Kentron cross-ref #{km['id']} reverse geocode ({rev['display_name'][:80]})",
            })

    # --- Signal 2: Direct reverse geocode of listing coords ---
    if lid not in rev_cache:
        if lat and lng:
            print(f"  Reverse-geocoding listing coords...")
            rev_cache[lid] = reverse_geocode(lat, lng)
    rev = rev_cache.get(lid, {})
    if rev.get("house_number"):
        road_matches = _streets_match(street, rev.get("road", ""))
        if road_matches:
            candidates.append({
                "address": f"{rev['house_number']} {rev['road']}",
                "confidence": "HIGH",
                "source": f"Nominatim reverse geocode, road matches listing street ({rev['display_name'][:80]})",
            })
        else:
            candidates.append({
                "address": f"{rev['house_number']} {rev['road']}",
                "confidence": "LOW",
                "source": f"Nominatim reverse (road mismatch: listing={street}, reverse={rev['road']})",
            })
    elif rev.get("road"):
        candidates.append({
            "address": f"{rev['road']}",
            "confidence": "LOW",
            "source": f"Nominatim reverse, no house number ({rev['display_name'][:80]})",
        })

    # --- Signal 3: Description parsing ---
    desc_num = _parse_description_for_number(desc, street)
    if desc_num:
        candidates.append({
            "address": f"{desc_num} {street}",
            "confidence": "MEDIUM",
            "source": f"Parsed from listing description",
        })

    # --- Signal 4: AI vision on first 2 photos (only if we have an API client and no HIGH yet) ---
    has_high = any(c["confidence"] == "HIGH" for c in candidates)
    if ai_client and not has_high:
        photos = (listing.get("photo_urls") or [])[:2]
        if photos:
            ai_result = _ai_resolve(listing, rev, photos, ai_client)
            if ai_result and ai_result.get("address", "UNKNOWN") != "UNKNOWN":
                candidates.append(ai_result)

    # --- Pick best candidate ---
    priority = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    candidates.sort(key=lambda c: priority.get(c.get("confidence", "LOW"), 0), reverse=True)

    if candidates:
        best = candidates[0]
        return {
            "resolved_address": best["address"],
            "resolved_address_confidence": best["confidence"],
            "resolved_address_source": best["source"],
        }

    return {
        "resolved_address": None,
        "resolved_address_confidence": "LOW",
        "resolved_address_source": "No signals available",
    }


def _ai_resolve(listing: dict, rev_info: dict, photos: list[str], client) -> dict | None:
    """Use AI vision on exterior photos to try to identify building number."""
    street = listing.get("street") or "?"
    district = listing.get("district") or "?"
    rev_road = rev_info.get("road", "?")
    rev_house = rev_info.get("house_number", "?")

    text = f"""Property on {street}, {district} district, Yerevan.
Nearest reverse-geocoded address: {rev_house} {rev_road}.
Look at these exterior photos. Can you see any building number, house number, gate number, or address plate?
Reply with ONLY: ADDRESS: <number street> or ADDRESS: UNKNOWN"""

    content: list = [{"type": "text", "text": text}]
    for url in photos:
        if url and isinstance(url, str):
            content.append({"type": "image_url", "image_url": {"url": url}})

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": content}],
                max_tokens=100,
            )
            raw = (response.choices[0].message.content or "").strip()
            m = re.search(r"ADDRESS:\s*(.+?)(?:\n|$)", raw, re.I)
            addr = m.group(1).strip() if m else "UNKNOWN"
            if addr.upper() == "UNKNOWN":
                return None
            return {
                "address": addr,
                "confidence": "MEDIUM",
                "source": "AI vision identified from listing photos",
            }
        except Exception as e:
            if "429" in str(e).lower():
                time.sleep(10 * (attempt + 1))
                continue
            return None
    return None


def main():
    parser = argparse.ArgumentParser(description="Resolve exact addresses for favorite listings")
    parser.add_argument("--ids", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--copy-frontend", action="store_true")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI vision (faster, data-only)")
    args = parser.parse_args()

    ai_client = None
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key and not args.skip_ai:
        from openai import OpenAI
        ai_client = OpenAI(api_key=api_key)
        print("AI vision enabled (GPT-4o)")
    else:
        print("AI vision disabled (data-only mode)")

    listings_path = Path("data/listings.json")
    listings = json.loads(listings_path.read_text(encoding="utf-8"))
    favs = json.loads(Path("frontend/public/data/shortlist.json").read_text(encoding="utf-8"))

    by_url = {l["url"]: l for l in listings}
    id_to_idx = {l["id"]: i for i, l in enumerate(listings)}

    # Load reverse geocode cache (normalize legacy key names)
    rev_cache_path = Path("data/reverse_geocode_favs.json")
    rev_cache: dict = {}
    if rev_cache_path.exists():
        for item in json.loads(rev_cache_path.read_text()):
            normalized = {
                "road": item.get("road") or item.get("reverse_road", ""),
                "house_number": item.get("house_number") or item.get("reverse_house_number", ""),
                "display_name": item.get("display_name") or item.get("reverse_display", ""),
                "suburb": item.get("suburb") or item.get("reverse_suburb", ""),
                "postcode": item.get("postcode", ""),
                "id": item.get("id"),
            }
            rev_cache[item.get("id", item.get("listing_id"))] = normalized

    # Build Kentron cross-reference
    kentron = [l for l in listings if l.get("source") == "kentron"]
    kentron_by_street: dict[str, list[dict]] = {}
    for k in kentron:
        key = _normalize_street(k.get("street") or "")
        if key:
            kentron_by_street.setdefault(key, []).append(k)

    targets = []
    for url in favs:
        l = by_url.get(url)
        if l:
            targets.append(l)

    if args.ids:
        id_set = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        targets = [t for t in targets if t["id"] in id_set]

    print(f"\nResolving addresses for {len(targets)} listings...\n")

    for i, listing in enumerate(targets, 1):
        lid = listing["id"]
        street = listing.get("street") or "?"
        print(f"[{i}/{len(targets)}] id={lid} {street}")

        result = resolve_listing(listing, kentron_by_street, rev_cache, ai_client)

        addr = result.get("resolved_address") or "UNKNOWN"
        conf = result.get("resolved_address_confidence", "LOW")
        src = result.get("resolved_address_source", "")
        print(f"  -> {addr} ({conf})")
        if src:
            print(f"     {src[:120]}")

        if not args.dry_run:
            idx = id_to_idx.get(lid)
            if idx is not None:
                listings[idx]["resolved_address"] = result.get("resolved_address")
                listings[idx]["resolved_address_confidence"] = conf
                listings[idx]["resolved_address_source"] = src[:300] if src else None

    if not args.dry_run:
        with open(listings_path, "w", encoding="utf-8") as f:
            json.dump(listings, f, indent=2, ensure_ascii=False)
        print(f"\nSaved to {listings_path}")

        if args.copy_frontend:
            import shutil
            front = Path("frontend/public/data/listings.json")
            front.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(listings_path, front)
            print(f"Copied to {front}")

    # Save reverse geocode cache
    with open(rev_cache_path, "w", encoding="utf-8") as f:
        json.dump(list(rev_cache.values()), f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
