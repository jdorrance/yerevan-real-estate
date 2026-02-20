import csv
import json
from pathlib import Path

OUTPUT_DIR = Path("data/output")

CSV_COLUMNS = [
    "id",
    "url",
    "price_usd",
    "building_area_sqm",
    "land_area_sqm",
    "street",
    "address",
    "district",
    "city",
    "rooms",
    "bathrooms",
    "ceiling_height_m",
    "floors",
    "building_type",
    "condition",
    "facilities",
    "amenities",
    "description",
    "photo_urls",
    "photo_count",
    "lat",
    "lng",
    "geocode_precision",
    "maps_url",
]


def generate_csv(listings: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "listings.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for listing in listings:
            row = {**listing}
            if row.get("lat") and row.get("lng"):
                row["maps_url"] = (
                    f"https://www.google.com/maps?q={row['lat']},{row['lng']}"
                )
            else:
                row["maps_url"] = ""

            number = row.get("parsed_address_number", "")
            street = row.get("street", "")
            row["address"] = f"{number} {street}".strip() if number else street

            if isinstance(row.get("facilities"), list):
                row["facilities"] = "; ".join(row["facilities"])
            if isinstance(row.get("amenities"), list):
                row["amenities"] = "; ".join(row["amenities"])
            if isinstance(row.get("photo_urls"), list):
                row["photo_urls"] = "; ".join(row["photo_urls"])

            writer.writerow(row)

    print(f"  CSV saved to {path}")


def generate_geojson(listings: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "listings.geojson"

    features = []
    for listing in listings:
        lat = listing.get("lat")
        lng = listing.get("lng")
        if lat is None or lng is None:
            continue

        properties = {k: v for k, v in listing.items() if k not in ("lat", "lng")}
        number = listing.get("parsed_address_number", "")
        street = listing.get("street", "")
        properties["address"] = f"{number} {street}".strip() if number else street
        properties["maps_url"] = f"https://www.google.com/maps?q={lat},{lng}"

        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": properties,
        }
        features.append(feature)

    collection = {"type": "FeatureCollection", "features": features}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent=2, ensure_ascii=False)

    print(f"  GeoJSON saved to {path} ({len(features)} features)")

