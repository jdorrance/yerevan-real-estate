import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.real-estate.am"
SEARCH_URL = (
    f"{BASE_URL}/en/filtered-properties?"
    "propertyActionType=RENT&propertyTypes=HOUSE&regionIds=5&districtIds=60%2C61%2C64%2C66%2C67%2C73"
)

RAW_DIR = Path("data/raw")
OUT_PATH = Path("data/kentron_listings.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
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


def scrape_search_pages() -> list[str]:
    """
    Scrape the Kentron (real-estate.am) search listing pages and return a stable list of detail URLs.
    """
    urls: set[str] = set()
    page = 1
    while True:
        url = SEARCH_URL if page == 1 else f"{SEARCH_URL}&page={page}"
        print(f"  [Kentron] Fetching search page {page}...")
        cache = f"kentron_search_page_{page}.html"
        html = fetch_page(url, cache_name=cache)

        soup = BeautifulSoup(html, "html.parser")
        links = soup.find_all("a", href=re.compile(r"^/en/prp/house/rent/.+/\d+$"))
        page_urls = set()
        for a in links:
            href = a.get("href") or ""
            if not href:
                continue
            page_urls.add(urljoin(BASE_URL, href))

        if not page_urls:
            break

        before = len(urls)
        urls.update(page_urls)
        added = len(urls) - before
        print(f"    Found {len(page_urls)} listing links ({added} new)")
        page += 1

    return sorted(urls)


def _extract_address_coords(html: str) -> tuple[float | None, float | None]:
    """
    real-estate.am embeds address coordinates inside an escaped JSON payload (used for the Yandex map).

    We extract the property-level pin at: address.latitude / address.longitude.
    """
    # The page is a Next.js app and the coordinates live in an embedded JSON-ish payload.
    # Rather than matching exact backslash-escape sequences, we match the semantic shape:
    #   address ... latitude <number> ... longitude <number>
    m = re.search(
        r"address.{0,200}?latitude[^0-9]{0,50}([0-9]{2}\.[0-9]{4,}).{0,200}?longitude[^0-9]{0,50}([0-9]{2}\.[0-9]{4,})",
        html,
        flags=re.I | re.S,
    )
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except Exception:
        return None, None


def _extract_photos(html: str) -> list[str]:
    """
    Extract photo UUIDs/hashes and return LARGE image URLs.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r"https?://s\.kentronrealty\.am/images/property/(?:SMALL|MEDIUM)/([^\"'\s>]+?\.webp)",
        html,
        flags=re.I,
    ):
        filename = m.group(1).rstrip("\\")
        if not filename or filename in seen:
            continue
        seen.add(filename)
        urls.append(f"https://s.kentronrealty.am/images/property/LARGE/{filename}")
    return urls


def _extract_from_meta_description(meta_desc: str) -> dict:
    """
    Parse structured bits that appear in the <meta name=\"description\"> content, e.g.:
      \"..., 900 sq.m land area, 400 sq.m house area, 3 floor, 3 bathroom, renovated.\"
    """
    out: dict = {}

    m = re.search(r"(\d+(?:\.\d+)?)\s*sq\.m\s*land area", meta_desc, re.I)
    if m:
        out["land_area_sqm"] = int(float(m.group(1)))

    m = re.search(r"(\d+(?:\.\d+)?)\s*sq\.m\s*house area", meta_desc, re.I)
    if m:
        out["building_area_sqm"] = int(float(m.group(1)))

    m = re.search(r"(\d+(?:\.\d+)?)\s*floor", meta_desc, re.I)
    if m:
        out["floors"] = int(float(m.group(1)))

    m = re.search(r"(\d+(?:\.\d+)?)\s*bathroom", meta_desc, re.I)
    if m:
        out["bathrooms"] = int(float(m.group(1)))

    # Condition is commonly present as the last adjective in this sentence.
    # Keep it simple: if we see specific known conditions, record them.
    if re.search(r"\brenovated\b", meta_desc, re.I):
        out["condition"] = "Renovated"
    elif re.search(r"\bgood condition\b", meta_desc, re.I):
        out["condition"] = "Good condition"
    elif re.search(r"\bzero condition\b", meta_desc, re.I):
        out["condition"] = "Zero condition"
    elif re.search(r"\bnew construction\b", meta_desc, re.I):
        out["condition"] = "New construction"

    return out


def parse_detail_page(detail_url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # ID = numeric last segment in URL.
    m = re.search(r"/(\d+)$", detail_url)
    listing_id = int(m.group(1)) if m else None

    data: dict = {
        "id": listing_id,
        "url": detail_url,
        "source": "kentron",
        "city": "Yerevan",
        "district": "",
        "street": "",
        "title": "",
        "price_usd": None,
        "rooms": None,
        "bathrooms": None,
        "floors": None,
        "building_area_sqm": None,
        "land_area_sqm": None,
        "ceiling_height_m": None,
        "building_type": None,
        "condition": None,
        "facilities": [],
        "amenities": [],
        "description": "",
        "photo_urls": [],
        "photo_count": 0,
        "parsed_address_number": None,
        "lat": None,
        "lng": None,
        "geocode_precision": "failed",
    }

    title_tag = soup.find("title")
    if title_tag:
        data["title"] = title_tag.get_text(" ", strip=True)

    # h1: usually \"7-room house for rent Sundukyan street\".
    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(" ", strip=True)
        rm = re.search(r"(\d+)\s*-\s*room", h1_text, re.I)
        if rm:
            data["rooms"] = int(rm.group(1))

    # h2: usually \"Sundukyan street, Arabkir, Yerevan\".
    h2 = soup.find("h2")
    if h2:
        loc = h2.get_text(" ", strip=True)
        parts = [p.strip() for p in loc.split(",") if p.strip()]
        if len(parts) >= 2:
            data["street"] = parts[0]
            data["district"] = parts[1]
        if len(parts) >= 3:
            data["city"] = parts[2]

    # Price (USD).
    price_el = soup.find(string=re.compile(r"\$\s*[\d,]+"))
    if price_el:
        pm = re.search(r"\$\s*([\d,]+)", str(price_el))
        if pm:
            data["price_usd"] = int(pm.group(1).replace(",", ""))

    # Metrics, type, condition often appear in meta description content.
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        md = meta_desc["content"]
        data.update(_extract_from_meta_description(md))

        # Try to recover rooms if missing (\"7 room House for rent ...\").
        if data.get("rooms") is None:
            rm = re.search(r"(\d+)\s*room", md, re.I)
            if rm:
                data["rooms"] = int(rm.group(1))

        # Building type is sometimes present as \"Stone\" in the visible UI; parse conservatively from meta too.
        bt = re.search(r"\b(monolith|panel|stone|other)\b", md, re.I)
        if bt:
            data["building_type"] = bt.group(1).capitalize()

    # Ceiling height appears in visible UI as \"3.2m\" (not in meta description).
    tm = re.search(r"\b(\d+(?:\.\d+)?)m\b", soup.get_text(" ", strip=True))
    if tm:
        try:
            data["ceiling_height_m"] = float(tm.group(1))
        except Exception:
            pass

    # Building type and condition appear as standalone words in the main text too.
    # Keep it conservative: only set if currently missing and match known tokens.
    page_text = soup.get_text(" ", strip=True)
    if data.get("building_type") is None:
        bt = re.search(r"\b(Stone|Monolith|Panel|Other)\b", page_text)
        if bt:
            data["building_type"] = bt.group(1)
    if data.get("condition") is None:
        cd = re.search(r"\b(Renovated|Good condition|Zero condition|New construction)\b", page_text, re.I)
        if cd:
            # Normalize casing to match site strings.
            data["condition"] = cd.group(1)[0].upper() + cd.group(1)[1:].lower()

    # Coordinates from embedded JSON (Yandex pin position).
    lat, lng = _extract_address_coords(html)
    if lat is not None and lng is not None:
        data["lat"] = lat
        data["lng"] = lng
        data["geocode_precision"] = "source_map"

    # Photos.
    photo_urls = _extract_photos(html)
    data["photo_urls"] = photo_urls
    data["photo_count"] = len(photo_urls)

    # Conveniences lists.
    conv = None
    for hdr in soup.find_all(["h2", "h3", "h4"]):
        if hdr.get_text(" ", strip=True).lower() == "conveniences":
            conv = hdr
            break
    if conv:
        section = conv.find_parent()
        current: list[str] | None = None
        for node in section.find_all(["h3", "p", "span", "li"]):
            if node.name == "h3":
                name = node.get_text(" ", strip=True).lower()
                if name == "basic amenities":
                    current = data["facilities"]
                    continue
                if name == "additional amenities":
                    current = data["amenities"]
                    continue
                current = None
                continue

            if current is None:
                continue
            t = node.get_text(" ", strip=True)
            if not t:
                continue
            # Keep only small leaf-like tokens.
            if len(t) > 60:
                continue
            if t not in current:
                current.append(t)

    return data


def scrape_all_details(detail_urls: list[str]) -> list[dict]:
    out: list[dict] = []
    total = len(detail_urls)
    for i, url in enumerate(detail_urls, 1):
        m = re.search(r"/(\d+)$", url)
        lid = m.group(1) if m else "unknown"
        print(f"  [Kentron] [{i}/{total}] Fetching detail #{lid}...")
        cache = f"kentron_detail_{lid}.html"
        html = fetch_page(url, cache_name=cache)
        out.append(parse_detail_page(url, html))
    return out


def run_kentron_scraper() -> list[dict]:
    """Main entry point: scrape search + details for real-estate.am, return structured data."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    existing: dict[int, dict] = {}
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            for item in json.load(f):
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    existing[item["id"]] = item
        print(f"  Loaded {len(existing)} cached Kentron listings")

    detail_urls = scrape_search_pages()
    ids = []
    for url in detail_urls:
        m = re.search(r"/(\d+)$", url)
        if m:
            ids.append(int(m.group(1)))
    ids_set = set(ids)
    print(f"  Total unique Kentron listings found: {len(ids_set)}")

    new_urls: list[str] = []
    for u in detail_urls:
        m = re.search(r"/(\d+)$", u)
        if not m:
            continue
        lid = int(m.group(1))
        prev = existing.get(lid)
        # Re-fetch if missing the source-map coords (or listing is new).
        if (
            not prev
            or prev.get("lat") is None
            or prev.get("lng") is None
            or prev.get("geocode_precision") != "source_map"
        ):
            new_urls.append(u)

    skip_count = len(detail_urls) - len(new_urls)
    print(f"  Kentron listings to fetch: {len(new_urls)} (skipping {skip_count} cached)")

    if new_urls:
        new_listings = scrape_all_details(new_urls)
        for l in new_listings:
            if isinstance(l, dict) and isinstance(l.get("id"), int):
                existing[l["id"]] = l

    # Preserve the stable ordering from the search pages.
    listings = []
    for url in detail_urls:
        m = re.search(r"/(\d+)$", url)
        if not m:
            continue
        lid = int(m.group(1))
        if lid in existing:
            listings.append(existing[lid])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved {len(listings)} Kentron listings to {OUT_PATH}")

    return listings

