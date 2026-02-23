#!/usr/bin/env python3
"""
Yerevan Housing Rental Index Pipeline

Scrapes rental listings from besthouse.am, geocodes them,
and generates CSV + GeoJSON. The interactive map UI is served
as a static Vite frontend (see frontend/).
"""
import json
from pathlib import Path
import shutil

from scraper import run_scraper
from scraper_kentron import run_kentron_scraper
from scraper_listam import run_listam_scraper
from geocode import in_district_bbox, run_geocoder
from spread import run_spread
from isochrones import maybe_write_isochrones
from greens import write_greens_geojson
from output import generate_csv, generate_geojson


def _reset_bad_geocodes_for_regen(listings: list[dict]) -> int:
    """
    Clear lat/lng so the improved district-aware geocoder can re-run.

    Untouched: source_map (Kentron embedded coords), overrides, address-precision.
    Reset: district / district_jitter precision (always); street-level results that
    land outside the district bbox (likely wrong-district geocoding).
    """
    protected = {"source_map", "source_approx", "override", "address"}
    cleared = 0
    for l in listings:
        prec = (l.get("geocode_precision") or "").strip()

        if prec in protected:
            continue

        if prec in {"district", "district_jitter"}:
            if l.get("lat") is not None or l.get("lng") is not None or l.get("geocode_precision"):
                l["lat"] = None
                l["lng"] = None
                l["geocode_precision"] = None
                cleared += 1
            continue

        lat = l.get("lat")
        lng = l.get("lng")
        district = l.get("district") or ""
        if lat is None or lng is None or not district:
            continue

        # For street-level results, check against the district bbox.
        # False positives (e.g. Vahagni's tight bbox) just cause an extra re-geocode,
        # which is harmless.  False negatives (miss a wrong result) are the bigger risk.
        ok = in_district_bbox(lat, lng, district)
        if ok is False:
            l["lat"] = None
            l["lng"] = None
            l["geocode_precision"] = None
            cleared += 1

    return cleared


def main():
    print("=" * 60)
    print("  Yerevan Housing Rental Index Pipeline")
    print("=" * 60)

    listings_path = Path("data/listings.json")

    prev_by_id: dict[int, dict] = {}
    if listings_path.exists():
        try:
            with open(listings_path, encoding="utf-8") as f:
                for item in json.load(f):
                    if isinstance(item, dict) and isinstance(item.get("id"), int):
                        prev_by_id[item["id"]] = item
            print(f"\n  Loaded {len(prev_by_id)} previous unified listings (for carry-forward fields)")
        except Exception:
            prev_by_id = {}

    print("\n[1a/4] SCRAPING (besthouse.am)")
    besthouse = run_scraper()

    print("\n[1b/4] SCRAPING (real-estate.am / Kentron)")
    kentron = run_kentron_scraper()

    print("\n[1c/4] SCRAPING (list.am)")
    listam = run_listam_scraper()

    listings = besthouse + kentron + listam

    # Carry forward computed fields from the previous unified output (AI review + geo coords).
    if prev_by_id:
        for l in listings:
            pid = l.get("id")
            if not isinstance(pid, int):
                continue
            prev = prev_by_id.get(pid)
            if not prev:
                continue

            # AI fields
            if (not (l.get("ai_summary") or "").strip()) and (prev.get("ai_summary") or "").strip():
                l["ai_summary"] = prev.get("ai_summary")
            if l.get("ai_score") is None and prev.get("ai_score") is not None:
                l["ai_score"] = prev.get("ai_score")

            # Geo fields (avoid re-geocoding)
            if l.get("lat") is None and prev.get("lat") is not None:
                l["lat"] = prev.get("lat")
            if l.get("lng") is None and prev.get("lng") is not None:
                l["lng"] = prev.get("lng")
            if (not l.get("geocode_precision")) and prev.get("geocode_precision"):
                l["geocode_precision"] = prev.get("geocode_precision")

    reset_count = _reset_bad_geocodes_for_regen(listings)
    if reset_count:
        print(f"\n  Reset {reset_count} listings for re-geocoding (district precision / out-of-district)")

    print("\n[2/4] GEOCODING")
    not_geocoded = [l for l in listings if l.get("lat") is None]
    if not_geocoded:
        print(f"  {len(not_geocoded)} listings need geocoding...")
        listings, eu_coords = run_geocoder(listings)
    else:
        print(f"  All {len(listings)} already geocoded, skipping.")
        eu_coords = (40.1862324, 44.5047339)

    print("\n[3/4] SPREADING")
    listings = run_spread(listings)

    # Always persist the current listings (and spread coords) for the frontend to consume.
    listings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(listings_path, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)

    print("\n[4/4] GENERATING OUTPUTS")
    generate_csv(listings)
    generate_geojson(listings)

    # Copy data for the static frontend (GitHub Pages friendly).
    frontend_data_dir = Path("frontend/public/data")
    frontend_data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(listings_path, frontend_data_dir / "listings.json")
    with open(frontend_data_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump({"eu": {"lat": eu_coords[0], "lng": eu_coords[1]}}, f, indent=2)

    # Optional: generate walking isochrones (15/30 minutes).
    wrote_iso = maybe_write_isochrones(
        center_lat=eu_coords[0],
        center_lng=eu_coords[1],
        out_path=frontend_data_dir / "isochrones.geojson",
        minutes=(15, 30),
        force=True,
    )
    if wrote_iso:
        print("  Wrote frontend/public/data/isochrones.geojson (walking isochrones)")
    else:
        # Keep any previously-committed isochrones.geojson in place.
        pass

    wrote_greens = write_greens_geojson(out_path=frontend_data_dir / "greens.geojson", force=True)
    if wrote_greens:
        print("  Wrote frontend/public/data/greens.geojson (parks/greens)")

    total = len(listings)
    geocoded = sum(1 for l in listings if l.get("lat"))
    photos_total = sum(l.get("photo_count", 0) for l in listings)

    print(f"\n  SUMMARY")
    print(f"  Total listings: {total}")
    print(f"  Geocoded: {geocoded}/{total}")
    print(f"  Total photos indexed: {photos_total}")
    print(f"\n  Outputs:")
    print(f"    data/output/listings.csv")
    print(f"    data/output/listings.geojson")
    print(f"    frontend/public/data/listings.json")
    print(f"    frontend/public/data/config.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
