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
from geocode import run_geocoder
from spread import run_spread
from isochrones import maybe_write_isochrones
from output import generate_csv, generate_geojson


def main():
    print("=" * 60)
    print("  Yerevan Housing Rental Index Pipeline")
    print("=" * 60)

    listings_path = Path("data/listings.json")

    print("\n[1/3] SCRAPING")
    listings = run_scraper()

    print("\n[2/3] GEOCODING")
    not_geocoded = [l for l in listings if l.get("lat") is None]
    if not_geocoded:
        print(f"  {len(not_geocoded)} listings need geocoding...")
        listings, eu_coords = run_geocoder(listings)
    else:
        print(f"  All {len(listings)} already geocoded, skipping.")
        eu_coords = (40.1862324, 44.5047339)

    print("\n[2.5/3] SPREADING")
    listings = run_spread(listings)

    # Always persist the current listings (and spread coords) for the frontend to consume.
    listings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(listings_path, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)

    print("\n[3/3] GENERATING OUTPUTS")
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
