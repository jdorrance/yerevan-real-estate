import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright

BASE_URL = "https://www.list.am"
RAW_DIR = Path("data/raw")
OUT_PATH = Path("data/listam_listings.json")

# list.am is fronted by Cloudflare; use a real browser and be conservative.
REQUEST_DELAY = 1.5

# Houses for rent category in Yerevan.
# Use the exact query shape the user provided (URL-encoded commas).
SEARCH_PATH = "/en/category/1378"
SEARCH_QUERY = (
    "n=1%2C2%2C3%2C4%2C5%2C6%2C7%2C8%2C9%2C10%2C13%2C11%2C12"
    "&cmtype=&crc=&price1=1500&price2="
    "&_a136_1=200&_a136_2=&_a5=&_a34=&_a37=&_a76=&_a78=&_a35_1=&_a35_2=&_a68=&_a69="
)

# Map list.am district labels to our unified naming (besthouse spelling).
DISTRICT_MAP = {
    "Ajapnyak": "Achapnyak",
    "Kentron": "Center",
    "Nor Nork": "Nor Norq",
}


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "x"


def _canonical_listam_url(href: str) -> str:
    """
    Normalize list.am item URLs:
      - keep scheme+host
      - drop query/fragment
    """
    full = urljoin(BASE_URL, href)
    p = urlparse(full)
    return f"{p.scheme}://{p.netloc}{p.path}"


def _maybe_int(s: str) -> int | None:
    m = re.search(r"(\d+)", s.replace(",", ""))
    return int(m.group(1)) if m else None


def _maybe_float(s: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", s.replace(",", ""))
    return float(m.group(1)) if m else None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _extract_photo_urls(html: str) -> list[str]:
    # Full-size photos are present in the JS init block as protocol-relative URLs.
    urls = re.findall(r"//s\.list\.am/f/\d+/\d+\.webp", html, flags=re.I)
    urls = [f"https:{u}" for u in urls]
    return _dedupe_preserve_order(urls)


def _extract_coords(html: str) -> tuple[float | None, float | None]:
    # Approximate listing location is embedded in pl1.init("poiMap", LAT, LNG, ...).
    m = re.search(
        r'pl1\.init\("poiMap",\s*([0-9]{2}\.[0-9]+),\s*([0-9]{2}\.[0-9]+)',
        html,
        flags=re.I,
    )
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except Exception:
        return None, None


def _extract_dates(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    listed_iso: str | None = None
    renewed: str | None = None

    posted = soup.select_one('span[itemprop="datePosted"]')
    if posted and posted.get("content"):
        listed_iso = str(posted.get("content")).strip() or None

    footer = soup.select_one("div.footer")
    if footer:
        for sp in footer.find_all("span"):
            t = sp.get_text(" ", strip=True)
            if t.lower().startswith("renewed "):
                renewed = t[len("Renewed ") :].strip() or None
                break

    return listed_iso, renewed


def _extract_location(soup: BeautifulSoup) -> tuple[str, str]:
    """
    Returns (street, city).

    list.am shows street + city but does NOT include the district on the detail page.
    """
    city = "Yerevan"
    street = ""

    p = soup.select_one("div.post-location-title p")
    if not p:
        p = soup.select_one("#poi-map-anchor")
    if p:
        loc = p.get_text(" ", strip=True)
        # Typically: "Tolstoy Street, Yerevan"
        parts = [x.strip() for x in loc.split(",") if x.strip()]
        if parts:
            street = parts[0]
        if len(parts) >= 2:
            city = parts[-1]

    return street, city


def _parse_bordered_metrics(soup: BeautifulSoup) -> dict:
    """
    Parses the bordered attribute grid (house area, land area, floors, rooms, bathrooms).
    """
    out: dict = {}
    grid = soup.select_one("div.attr.g.new.bordered")
    if not grid:
        return out

    for at2 in grid.select("div.at2"):
        ps = at2.find_all("p")
        if len(ps) < 2:
            continue
        value = ps[0].get_text(" ", strip=True)
        label = ps[-1].get_text(" ", strip=True).lower()

        if "house area" in label:
            out["building_area_sqm"] = _maybe_int(value)
        elif "land area" in label:
            out["land_area_sqm"] = _maybe_int(value)
        elif "floors" in label:
            out["floors"] = _maybe_int(value)
        elif "number of rooms" in label or label.strip() == "rooms":
            out["rooms"] = _maybe_int(value)
        elif "number of bathrooms" in label or "bathrooms" in label:
            # Bathrooms can be "3+"
            out["bathrooms"] = _maybe_int(value)

    return out


def _parse_attr_section(section_el) -> list[dict]:
    """
    Parses a list.am attribute section that uses `div.attr.g.new` with `div.at2` items.

    Returns list of dicts:
      - {"kind": "kv", "label": str, "value": str}
      - {"kind": "bool", "label": str, "enabled": bool}
    """
    items: list[dict] = []
    if not section_el:
        return items

    for at2 in section_el.select("div.at2"):
        enabled = "disabled" not in (at2.get("class") or [])
        ps = at2.find_all("p")
        texts = [p.get_text(" ", strip=True) for p in ps if p.get_text(" ", strip=True)]
        if not texts:
            continue

        # Common patterns:
        #  - kv: [value, label] OR [label, value] depending on section.
        # We'll treat 2+ tokens as kv if it looks like that.
        if len(texts) >= 2:
            # In many sections, first is the value and last is label (as in bordered metrics).
            # But for other sections, label often appears first. We keep both; caller decides.
            items.append({"kind": "kv", "a": texts[0], "b": texts[-1], "enabled": enabled})
        else:
            items.append({"kind": "bool", "label": texts[0], "enabled": enabled})

    return items


def _find_section(soup: BeautifulSoup, header: str):
    hdr = None
    for gt in soup.select("div.gt"):
        t = gt.get_text(" ", strip=True).strip().lower()
        if t == header.strip().lower():
            hdr = gt
            break
    if not hdr:
        return None
    # The section content is usually the next sibling element.
    nxt = hdr.find_next_sibling()
    return nxt


def _extract_price_usd(soup: BeautifulSoup) -> int | None:
    price = soup.select_one('span[itemprop="price"]')
    if not price:
        return None
    raw = price.get("content")
    currency = None
    cur = price.select_one('meta[itemprop="priceCurrency"]')
    if cur and cur.get("content"):
        currency = str(cur.get("content")).strip().upper()

    if raw is None:
        return None

    try:
        amount = int(str(raw).strip().replace(",", ""))
    except Exception:
        amount = None

    if currency == "USD":
        return amount

    # For non-USD listings, list.am shows a converted USD value in `.priceConverted`.
    conv = soup.select_one("div.priceConverted")
    if conv:
        m = re.search(r"\$\s*([\d,]+)\s*monthly", conv.get_text(" ", strip=True), re.I)
        if m:
            return int(m.group(1).replace(",", ""))

    return None


def parse_detail_page(
    detail_url: str,
    html: str,
    *,
    district_from_search: str,
) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    m = re.search(r"/(?:en/)?item/(\d+)$", detail_url)
    listing_id = int(m.group(1)) if m else None

    listed_date, renewed_date = _extract_dates(soup)
    street, city = _extract_location(soup)
    photos = _extract_photo_urls(html)
    lat, lng = _extract_coords(html)
    metrics = _parse_bordered_metrics(soup)

    title_el = soup.select_one('h1[itemprop="name"]')
    title = title_el.get_text(" ", strip=True) if title_el else ""

    # Description: under "Description" header, list.am uses `.body`.
    desc = ""
    body = _find_section(soup, "Description")
    if body:
        # Some pages use `div.body`, others use a plain container.
        b = body.select_one("div.body") or body
        desc = b.get_text("\n", strip=True)

    facilities: list[str] = []
    amenities: list[str] = []

    # Appliances section: enabled tokens are facilities.
    appliances = _find_section(soup, "Appliances")
    for item in _parse_attr_section(appliances):
        if not item.get("enabled"):
            continue
        if item.get("kind") == "bool":
            token = (item.get("label") or "").strip()
        else:
            a = (item.get("a") or "").strip()
            b = (item.get("b") or "").strip()
            # Prefer the label-like token.
            token = b if b and not re.search(r"\d", b) else a
            token = token.strip()
        if token and token not in facilities:
            facilities.append(token)

    # House information: pick out construction type and renovation; everything else to amenities.
    building_type = None
    condition = None
    house_info = _find_section(soup, "House Information")
    for item in _parse_attr_section(house_info):
        if not item.get("enabled"):
            continue
        if item.get("kind") == "bool":
            lbl = (item.get("label") or "").strip()
            if lbl and lbl not in amenities:
                amenities.append(lbl)
            continue

        a = (item.get("a") or "").strip()
        b = (item.get("b") or "").strip()

        a_l = a.lower()
        b_l = b.lower()

        # list.am uses: first <p> = label (Construction Type), second <p> = value (Stone).
        if "construction type" in a_l:
            building_type = b or building_type
            continue
        if "construction type" in b_l:
            building_type = a or building_type
            continue
        if "renovation" in a_l:
            condition = b or condition
            continue
        if "renovation" in b_l:
            condition = a or condition
            continue

        # Generic KV -> amenities
        if a and b:
            # Prefer "Label: Value" ordering.
            label, value = (a, b) if len(a) >= len(b) else (b, a)
            s = f"{label}: {value}"
            if s not in amenities:
                amenities.append(s)

    # House rules and deal terms: store as amenities strings.
    for section_name in ("House Rules", "Deal Terms"):
        sec = _find_section(soup, section_name)
        for item in _parse_attr_section(sec):
            if not item.get("enabled"):
                continue
            a = (item.get("a") or "").strip()
            b = (item.get("b") or "").strip()
            if a and b:
                s = f"{section_name} - {b}: {a}"
                if s not in amenities:
                    amenities.append(s)

    data: dict = {
        "id": listing_id,
        "url": detail_url,
        "source": "listam",
        "city": city or "Yerevan",
        "district": district_from_search,
        "street": street,
        "title": title,
        "price_usd": _extract_price_usd(soup),
        "rooms": metrics.get("rooms"),
        "bathrooms": metrics.get("bathrooms"),
        "floors": metrics.get("floors"),
        "building_area_sqm": metrics.get("building_area_sqm"),
        "land_area_sqm": metrics.get("land_area_sqm"),
        "ceiling_height_m": None,
        "building_type": building_type,
        "condition": condition,
        "facilities": facilities,
        "amenities": amenities,
        "description": desc,
        "photo_urls": photos,
        "photo_count": len(photos),
        "parsed_address_number": None,
        "lat": lat,
        "lng": lng,
        "geocode_precision": "source_approx" if (lat is not None and lng is not None) else "failed",
        "listed_date": listed_date,
        "renewed_date": renewed_date,
    }
    return data


@dataclass(frozen=True)
class SearchHit:
    id: int
    url: str
    district: str
    search_title: str


def _map_district(raw: str) -> str:
    d = (raw or "").strip()
    return DISTRICT_MAP.get(d, d)


def scrape_search_pages(page: Page) -> list[SearchHit]:
    """
    Scrape list.am search listing pages and return a stable list of detail URLs with districts.

    Note: District is only present on the search result cards (div.at).
    """
    hits: list[SearchHit] = []
    seen: set[int] = set()

    page_num = 1
    next_url = f"{BASE_URL}{SEARCH_PATH}?{SEARCH_QUERY}"
    visited_urls: set[str] = set()

    while True:
        if next_url in visited_urls:
            # Safety valve: avoid loops if pagination links behave unexpectedly.
            break
        visited_urls.add(next_url)

        print(f"  [list.am] Fetching search page {page_num}...")
        cache_path = RAW_DIR / f"listam_search_page_{page_num}.html"
        # Always refresh search pages. Cloudflare / pagination can make stale caches misleading,
        # and search pages are relatively cheap to fetch compared to detail pages.
        time.sleep(REQUEST_DELAY)
        page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
        html = page.content()
        cache_path.write_text(html, encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("a.h[href*='/item/']")
        if not links:
            break

        for a in links:
            href = a.get("href") or ""
            m = re.search(r"/(?:en/)?item/(\d+)", href)
            if not m:
                continue
            lid = int(m.group(1))
            if lid in seen:
                continue
            seen.add(lid)

            at = a.select_one("div.at")
            district_raw = ""
            if at:
                t = at.get_text(" ", strip=True)
                # e.g. "Kentron, 2 rm."
                district_raw = (t.split(",")[0] if "," in t else t).strip()

            title_el = a.select_one("div.l")
            search_title = title_el.get_text(" ", strip=True) if title_el else ""
            detail_url = _canonical_listam_url(href)
            hits.append(SearchHit(id=lid, url=detail_url, district=_map_district(district_raw), search_title=search_title))

        # Follow "Next" pagination link.
        next_a = None
        for cand in soup.select("span.pp a"):
            if cand.get_text(" ", strip=True).lower().startswith("next"):
                next_a = cand
                break
        if not next_a or not next_a.get("href"):
            break

        next_url = urljoin(BASE_URL, next_a.get("href"))
        page_num += 1

    return hits


def _new_context(pw) -> BrowserContext:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="en-US",
    )
    return ctx


def run_listam_scraper() -> list[dict]:
    """Main entry point: scrape search + details for list.am, return structured data."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    existing: dict[int, dict] = {}
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            for item in json.load(f):
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    existing[item["id"]] = item
        print(f"  Loaded {len(existing)} cached list.am listings")

    with sync_playwright() as pw:
        ctx = _new_context(pw)
        page = ctx.new_page()

        # Avoid loading heavy resources (images/fonts/media).
        def _route(route, request):
            if request.resource_type in {"image", "media", "font"}:
                return route.abort()
            return route.continue_()

        page.route("**/*", _route)

        hits = scrape_search_pages(page)
        print(f"  Total unique list.am listings found: {len(hits)}")

        to_fetch: list[SearchHit] = []
        for h in hits:
            prev = existing.get(h.id)
            if not prev:
                to_fetch.append(h)
                continue
            # Re-fetch if missing core content (photos, coords, dates).
            if (
                not prev.get("photo_urls")
                or prev.get("lat") is None
                or prev.get("lng") is None
                or not prev.get("listed_date")
                or not prev.get("facilities")
                or prev.get("building_type") is None
                or prev.get("condition") is None
            ):
                to_fetch.append(h)

        print(f"  list.am listings to fetch: {len(to_fetch)} (skipping {len(hits) - len(to_fetch)} cached)")

        total = len(to_fetch)
        for i, h in enumerate(to_fetch, 1):
            print(f"  [list.am] [{i}/{total}] Fetching detail #{h.id}...")
            cache_name = f"listam_detail_{h.id}.html"
            cache_path = RAW_DIR / cache_name
            if cache_path.exists():
                html = cache_path.read_text(encoding="utf-8")
            else:
                time.sleep(REQUEST_DELAY)
                page.goto(h.url, wait_until="domcontentloaded", timeout=60000)
                html = page.content()
                cache_path.write_text(html, encoding="utf-8")

            data = parse_detail_page(h.url, html, district_from_search=h.district)
            if isinstance(data, dict) and isinstance(data.get("id"), int):
                # Fallback title from search if missing.
                if not (data.get("title") or "").strip() and h.search_title:
                    data["title"] = h.search_title
                existing[data["id"]] = data

        # Close browser
        ctx.close()

    # Preserve stable ordering from search pages.
    listings: list[dict] = []
    for h in hits:
        if h.id in existing:
            listings.append(existing[h.id])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved {len(listings)} list.am listings to {OUT_PATH}")
    return listings


if __name__ == "__main__":
    run_listam_scraper()

