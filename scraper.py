import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://besthouse.am"
SEARCH_BASE = (
    f"{BASE_URL}/en/search?"
    "estate_role_id=2&estate_region=1"
    "&currency_id=USD&estate_min_price=2000&estate_max_price=5000"
    "&estate_min_area=170&estate_type_id=2"
)
DISTRICTS = {
    1: "Center",
    2: "Arabkir",
    4: "Achapnyak",
    9: "Nor-Norq",
}
RAW_DIR = Path("data/raw")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_DELAY = 1.0


def fetch_page(url: str, cache_name: str | None = None) -> str:
    if cache_name:
        cache_path = RAW_DIR / cache_name
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

    time.sleep(REQUEST_DELAY)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    if cache_name:
        cache_path = RAW_DIR / cache_name
        cache_path.write_text(html, encoding="utf-8")

    return html


def scrape_search_pages() -> list[int]:
    """Scrape all search result pages for all districts, return list of listing IDs."""
    all_ids = set()

    for district_id, district_name in DISTRICTS.items():
        search_url = f"{SEARCH_BASE}&estate_districts%5B%5D={district_id}"
        page = 1
        district_ids = set()

        while True:
            url = search_url if page == 1 else f"{search_url}&page={page}"
            print(f"  [{district_name}] Fetching search page {page}...")
            cache = f"search_{district_name.lower().replace('-','_')}_page_{page}.html"
            html = fetch_page(url, cache_name=cache)
            soup = BeautifulSoup(html, "html.parser")

            links = soup.find_all("a", href=re.compile(r"/rent-house-[^/]+/\d+$"))
            ids_on_page = set()
            for link in links:
                match = re.search(r"/(\d+)$", link["href"])
                if match:
                    ids_on_page.add(int(match.group(1)))

            if not ids_on_page:
                break

            district_ids.update(ids_on_page)
            print(f"    Found {len(ids_on_page)} listings on page")

            next_link = soup.find("a", string=re.compile(r"Next"))
            if not next_link:
                break
            page += 1

        new = district_ids - all_ids
        all_ids.update(district_ids)
        print(f"  [{district_name}] {len(district_ids)} total, {len(new)} new unique")

    return sorted(all_ids)


def parse_detail_page(listing_id: int, html: str) -> dict:
    """Parse a detail page HTML into a structured dict."""
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "id": listing_id,
        "url": f"{BASE_URL}/en/estates/{listing_id}",
        "source": "besthouse",
    }

    title_tag = soup.find("title")
    data["title"] = title_tag.text.strip() if title_tag else ""

    h1 = soup.find("h1")
    if h1:
        location_div = h1.find_next_sibling("div") or h1.find_next("div")

    price_text = ""
    price_el = soup.find(string=re.compile(r"\$\s*[\d,]+"))
    if price_el:
        price_text = price_el.strip()
        match = re.search(r"\$\s*([\d,]+)", price_text)
        data["price_usd"] = int(match.group(1).replace(",", "")) if match else None
    else:
        data["price_usd"] = None

    data["city"] = "Yerevan"
    data["district"] = ""
    data["street"] = ""

    loc_candidates = soup.find_all(string=re.compile(r"^Yerevan,\s*\w+"))
    for lc in loc_candidates:
        text = lc.strip()
        if len(text) < 80 and "," in text:
            parts = [p.strip() for p in text.split(",")]
            if len(parts) >= 3:
                data["city"] = parts[0]
                data["district"] = parts[1]
                data["street"] = parts[2]
                break

    if not data["street"]:
        title_text = data.get("title", "")
        match = re.match(r"\d+\s+room\s+\w+,\s*(.+?),\s*(.+?)\s*\((\w+)\)", title_text)
        if match:
            data["street"] = match.group(1).strip()
            data["district"] = match.group(2).strip()
            data["city"] = match.group(3).strip()

    data["bathrooms"] = None
    data["ceiling_height_m"] = None
    data["floors"] = None
    data["building_area_sqm"] = None
    data["land_area_sqm"] = None
    data["rooms"] = None

    h1 = soup.find("h1")
    if h1:
        parent_div = h1.find_parent("div")
        if parent_div:
            uls = parent_div.find_all("ul")
            for ul in uls:
                items = [li.get_text(strip=True) for li in ul.find_all("li")]
                if len(items) >= 4 and any("ROOM" in it for it in items):
                    for item in items:
                        if "ROOM" in item:
                            m = re.search(r"(\d+)\s*ROOM", item)
                            if m:
                                data["rooms"] = int(m.group(1))
                        elif "land" in item.lower() or "building" in item.lower():
                            lm = re.search(r"land\s*-\s*(\d+)", item, re.I)
                            bm = re.search(r"building\s*-\s*(\d+)", item, re.I)
                            if lm:
                                data["land_area_sqm"] = int(lm.group(1))
                            if bm:
                                data["building_area_sqm"] = int(bm.group(1))
                        elif re.match(r"^[\d.]+\s*m$", item):
                            hm = re.search(r"([\d.]+)\s*m", item)
                            if hm:
                                data["ceiling_height_m"] = float(hm.group(1))
                        elif re.match(r"^\d+\+?$", item):
                            val = item.rstrip("+")
                            num = int(val)
                            if data["rooms"] is not None and data["floors"] is None and num <= 10:
                                data["floors"] = int(item.rstrip("+"))
                            elif data["floors"] is not None and data["bathrooms"] is None:
                                data["bathrooms"] = item
                            elif data["rooms"] is None:
                                pass
                    if data["bathrooms"] is None:
                        for item in items:
                            if re.match(r"^\d+\+?$", item) and item != str(data.get("floors")):
                                data["bathrooms"] = item
                                break
                    break

    all_text = soup.get_text()

    if data["building_area_sqm"] is None:
        area_match = re.search(r"land\s*-\s*(\d+)\s*m\s*2?\s*,\s*building\s*-\s*(\d+)\s*m\s*2?", all_text, re.I)
        if area_match:
            data["land_area_sqm"] = int(area_match.group(1))
            data["building_area_sqm"] = int(area_match.group(2))

    if data["rooms"] is None:
        room_match = re.search(r"(\d+)\s*ROOM", all_text)
        if room_match:
            data["rooms"] = int(room_match.group(1))

    building_type_patterns = ["New construction", "Monolith", "Stone", "Panel"]
    data["building_type"] = None
    for bt in building_type_patterns:
        bt_section = soup.find(string=re.compile(r"BUILDING\s*TYPE", re.I))
        if bt_section:
            parent = bt_section.find_parent()
            if parent:
                next_el = parent.find_next_sibling()
                if next_el:
                    data["building_type"] = next_el.get_text(strip=True)
                    break

    condition_section = soup.find(string=re.compile(r"CONDITION", re.I))
    data["condition"] = None
    if condition_section:
        parent = condition_section.find_parent()
        if parent:
            next_el = parent.find_next_sibling()
            if next_el:
                data["condition"] = next_el.get_text(strip=True)

    data["facilities"] = []
    data["amenities"] = []
    facility_headers = soup.find_all(string=re.compile(r"FACILITIES", re.I))
    for fh in facility_headers:
        parent = fh.find_parent()
        if parent:
            container = parent.find_parent()
            if container:
                items = container.find_all("li")
                data["facilities"] = [item.get_text(strip=True) for item in items if item.get_text(strip=True)]
                break

    additional_headers = soup.find_all(string=re.compile(r"ADDITIONAL\s*INFORMATION", re.I))
    for ah in additional_headers:
        parent = ah.find_parent()
        if parent:
            container = parent.find_parent()
            if container:
                items = container.find_all("li")
                data["amenities"] = [item.get_text(strip=True) for item in items if item.get_text(strip=True)]
                break

    data["description"] = ""
    info_headers = soup.find_all(string=re.compile(r"^information$", re.I))
    for ih in info_headers:
        parent = ih.find_parent()
        if parent:
            container = parent.find_parent()
            if container:
                paragraphs = container.find_all("p")
                if paragraphs:
                    data["description"] = " ".join(p.get_text(strip=True) for p in paragraphs)
                elif container.find_next_sibling():
                    data["description"] = container.find_next_sibling().get_text(strip=True)
                break

    if not data["description"]:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            data["description"] = meta_desc["content"]

    image_base = f"objectstorage.eu-stockholm-1.oraclecloud.com/n/axmal8d79xjn/b/besthouse-public-001-prod/o/estates/{listing_id}/images/original/"
    photo_urls = []
    seen_hashes = set()
    for img_match in re.finditer(r'https?://objectstorage[^"\']+?/estates/\d+/images/original/([^"\'?\s]+)', html):
        full_url = img_match.group(0).split("?")[0]
        img_hash = img_match.group(1)
        if img_hash not in seen_hashes:
            seen_hashes.add(img_hash)
            photo_urls.append(full_url)

    if not photo_urls:
        for img_match in re.finditer(r'https?://objectstorage[^"\']+?/estates/\d+/images/([^"\'?\s]+)', html):
            full_url = img_match.group(0).split("?")[0]
            filename = img_match.group(1)
            if "original/" not in filename and filename not in seen_hashes:
                seen_hashes.add(filename)
                photo_urls.append(full_url)

    data["photo_urls"] = photo_urls
    data["photo_count"] = len(photo_urls)

    address_patterns = [
        re.compile(r"on\s+(\d+[\w]*)\s+([\w\s.'-]+?)(?:\s+(?:Street|St|street|str))", re.I),
        re.compile(r"at\s+(\d+[\w]*)\s+([\w\s.'-]+?)(?:\s+(?:Street|St|street|str))", re.I),
        re.compile(r"(\d+[\w]*)\s+([\w\s.'-]+?)(?:\s+(?:Street|St|street|str))[\s,.]", re.I),
    ]
    data["parsed_address_number"] = None
    desc_text = data.get("description", "")
    for pattern in address_patterns:
        match = pattern.search(desc_text)
        if match:
            data["parsed_address_number"] = match.group(1)
            break

    return data


def scrape_all_details(listing_ids: list[int]) -> list[dict]:
    """Fetch and parse detail pages for all listing IDs."""
    listings = []
    total = len(listing_ids)
    for i, lid in enumerate(listing_ids, 1):
        print(f"  [{i}/{total}] Fetching detail for listing #{lid}...")
        html = fetch_page(
            f"{BASE_URL}/en/estates/{lid}",
            cache_name=f"detail_{lid}.html",
        )
        listing = parse_detail_page(lid, html)
        listings.append(listing)
    return listings


def run_scraper() -> list[dict]:
    """Main entry point: scrape search + details, return structured data."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    output_path = Path("data/besthouse_listings.json")

    existing = {}
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for item in json.load(f):
                existing[item["id"]] = item
        print(f"  Loaded {len(existing)} cached listings")

    print("  Scraping search results across all districts...")
    listing_ids = scrape_search_pages()
    print(f"  Total unique listings found: {len(listing_ids)}")

    new_ids = [lid for lid in listing_ids if lid not in existing]
    print(f"  New listings to fetch: {len(new_ids)} (skipping {len(listing_ids) - len(new_ids)} cached)")

    if new_ids:
        print("\n  Scraping new detail pages...")
        new_listings = scrape_all_details(new_ids)
        for l in new_listings:
            existing[l["id"]] = l

    listings = [existing[lid] for lid in listing_ids if lid in existing]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved {len(listings)} listings to {output_path}")

    return listings


if __name__ == "__main__":
    run_scraper()
