#!/usr/bin/env python3
"""
Export shortlist listings to a CSV spreadsheet and frontend shortlist.json.
Reads listing IDs from shortlist_ids.txt (one ID per line) and data from data/listings.json.
"""

import csv
import json
from pathlib import Path

BASE = "https://besthouse.am/en/estates/"


def main() -> None:
    repo = Path(__file__).resolve().parent
    ids_path = repo / "shortlist_ids.txt"
    listings_path = repo / "data" / "listings.json"
    out_path = repo / "data" / "shortlist.csv"
    frontend_shortlist = repo / "frontend" / "public" / "data" / "shortlist.json"

    with open(ids_path, "r", encoding="utf-8") as f:
        id_list = [int(line.strip()) for line in f if line.strip()]
    id_set = set(id_list)
    id_order = {lid: i for i, lid in enumerate(id_list)}

    with open(listings_path, "r", encoding="utf-8") as f:
        all_listings = json.load(f)

    rows = [L for L in all_listings if isinstance(L, dict) and L.get("id") in id_set]
    rows.sort(key=lambda L: id_order.get(L["id"], 999))

    def cell(L: dict, key: str, default=""):
        v = L.get(key)
        if v is None:
            return default
        if isinstance(v, list):
            return "; ".join(str(x) for x in v)
        return str(v).strip()

    columns = [
        ("ID", "id"),
        ("Street", "street"),
        ("District", "district"),
        ("Price (USD/mo)", "price_usd"),
        ("URL", "url"),
        ("Rooms", "rooms"),
        ("Building (m²)", "building_area_sqm"),
        ("Land (m²)", "land_area_sqm"),
        ("Bathrooms", "bathrooms"),
        ("Floors", "floors"),
        ("Building type", "building_type"),
        ("Condition", "condition"),
        ("Ceiling (m)", "ceiling_height_m"),
        ("Facilities", "facilities"),
        ("Amenities", "amenities"),
        ("Photo count", "photo_count"),
        ("AI Score", "ai_score"),
        ("AI Summary", "ai_summary"),
        ("Description", "description"),
        ("Lat", "lat"),
        ("Lng", "lng"),
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([c[0] for c in columns])
        for L in rows:
            w.writerow([cell(L, c[1]) for c in columns])

    # Keep frontend shortlist.json in sync (used as default favorites when localStorage is empty)
    urls = [L.get("url") or f"{BASE}{L['id']}" for L in rows if L.get("id")]
    frontend_shortlist.parent.mkdir(parents=True, exist_ok=True)
    with open(frontend_shortlist, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2)

    print(f"Wrote {len(rows)} rows to {out_path} and {frontend_shortlist.name}")


if __name__ == "__main__":
    main()
