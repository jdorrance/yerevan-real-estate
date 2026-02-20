#!/usr/bin/env python3
"""
Run the AI review prompt on each listing (metadata + all images).
Writes ai_score (1-10) and ai_summary back into the listing JSON.

Usage:
  python review.py --limit 2              # test: 2 listings, sequential
  python review.py --limit 10 --parallel 8  # 10 listings, 8 at a time
  python review.py                          # all remaining, parallel 8

Requires OPENAI_API_KEY or ANTHROPIC_API_KEY. Skips listings that already have ai_summary.
"""

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SYSTEM_PROMPT = """You are a blunt, observant real estate reviewer helping an American/European expat couple with an infant (planning to get a dog) evaluate rental homes in Yerevan, Armenia.

Their priorities (in rough order):
1. Spacious — they want large rooms and generous total area
2. Yard / outdoor space — must be suitable for a dog, ideally with grass and a real fence (not just a concrete pad)
3. Near parks or green areas for walks with the stroller and dog
4. "Western-style" modern interiors — they dislike Soviet-era layouts, dark wood paneling, and cramped kitchens
5. Natural light, good condition, safe for a toddler
6. Prefer houses over apartments; balconies are nice but not a substitute for a yard

Respond in EXACTLY this format (no markdown, no extra lines):

SCORE: <integer 1-10>
REVIEW: <2-3 sentences>

Score guide:
- 9-10: Excellent fit — big yard, modern, green area, move-in ready
- 7-8: Strong candidate with minor compromises
- 5-6: Acceptable but notable drawbacks
- 3-4: Significant issues (no yard, Soviet interior, too small)
- 1-2: Dealbreaker (apartment, dark, no outdoor space)

Be specific about what you SEE in the photos — mention actual details (tile color, yard size, kitchen style, views, fence type, furniture quality, red flags). Don't be generic. If something is a dealbreaker or a standout, say so plainly."""


def build_user_content(listing: dict, max_images: int | None = None) -> list:
    """Build the 'content' array for the user message: one text part + one image part per photo URL."""
    facilities = listing.get("facilities") or []
    amenities = listing.get("amenities") or []
    if isinstance(facilities, list):
        facilities = ", ".join(facilities)
    if isinstance(amenities, list):
        amenities = ", ".join(amenities)
    desc = (listing.get("description") or "").strip() or "(no description)"
    urls = listing.get("photo_urls") or []
    if max_images is not None:
        urls = urls[:max_images]
    urls = [u for u in urls if u and isinstance(u, str)]

    text = f"""## Property: {listing.get('street') or '?'}, {listing.get('district') or '?'}
- Price: ${listing.get('price_usd') or '?'}/mo
- Building area: {listing.get('building_area_sqm')} m² | Land: {listing.get('land_area_sqm')} m²
- Rooms: {listing.get('rooms')} | Bathrooms: {listing.get('bathrooms')} | Floors: {listing.get('floors')}
- Building type: {listing.get('building_type') or '?'} | Condition: {listing.get('condition') or '?'}
- Ceiling height: {listing.get('ceiling_height_m')} m
- Facilities: {facilities}
- Amenities: {amenities}
- Description: {desc}

Review the following {len(urls)} photos of this property."""

    content = [{"type": "text", "text": text}]
    for url in urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def parse_response(text: str) -> tuple[int | None, str]:
    """Extract SCORE (1-10) and REVIEW text from model output."""
    score = None
    summary = ""
    score_m = re.search(r"SCORE:\s*(\d+)", text, re.IGNORECASE)
    if score_m:
        s = int(score_m.group(1))
        if 1 <= s <= 10:
            score = s
    review_m = re.search(r"REVIEW:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if review_m:
        summary = review_m.group(1).strip()
    return score, summary


def review_one_openai(listing: dict, client, max_images: int | None = None) -> dict:
    """Call OpenAI vision model for one listing."""
    content = build_user_content(listing, max_images=max_images)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        max_tokens=400,
    )
    raw = (response.choices[0].message.content or "").strip()
    score, summary = parse_response(raw)
    out = dict(listing)
    out["ai_score"] = score
    out["ai_summary"] = summary
    return out


def build_anthropic_content(listing: dict, max_images: int | None = None) -> list:
    """Anthropic content blocks: text first, then one image block per URL."""
    facilities = listing.get("facilities") or []
    amenities = listing.get("amenities") or []
    if isinstance(facilities, list):
        facilities = ", ".join(facilities)
    if isinstance(amenities, list):
        amenities = ", ".join(amenities)
    desc = (listing.get("description") or "").strip() or "(no description)"
    urls = listing.get("photo_urls") or []
    if max_images is not None:
        urls = urls[:max_images]
    urls = [u for u in urls if u and isinstance(u, str)]
    text = f"""## Property: {listing.get('street') or '?'}, {listing.get('district') or '?'}
- Price: ${listing.get('price_usd') or '?'}/mo
- Building area: {listing.get('building_area_sqm')} m² | Land: {listing.get('land_area_sqm')} m²
- Rooms: {listing.get('rooms')} | Bathrooms: {listing.get('bathrooms')} | Floors: {listing.get('floors')}
- Building type: {listing.get('building_type') or '?'} | Condition: {listing.get('condition') or '?'}
- Ceiling height: {listing.get('ceiling_height_m')} m
- Facilities: {facilities}
- Amenities: {amenities}
- Description: {desc}

Review the following {len(urls)} photos of this property."""
    blocks = [{"type": "text", "text": text}]
    for url in urls:
        blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    return blocks


def review_one_anthropic(listing: dict, client, max_images: int | None = None) -> dict:
    """Call Anthropic Claude vision model for one listing."""
    content = build_anthropic_content(listing, max_images=max_images)
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    raw = (response.content[0].text if response.content else "").strip()
    score, summary = parse_response(raw)
    out = dict(listing)
    out["ai_score"] = score
    out["ai_summary"] = summary
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="AI review listings with all images")
    parser.add_argument("--input", type=Path, default=Path("data/listings.json"), help="Listings JSON path")
    parser.add_argument("--limit", type=int, default=None, help="Max number of listings to process (default: all)")
    parser.add_argument("--parallel", type=int, default=8, help="Concurrent requests (default 8)")
    parser.add_argument("--skip-done", action="store_true", default=True, help="Skip listings that already have ai_summary")
    parser.add_argument("--copy-frontend", action="store_true", help="Copy output to frontend/public/data/listings.json")
    parser.add_argument("--max-images", type=int, default=None, help="Cap images per listing (e.g. 12) to stay under token limits")
    parser.add_argument("--ids", type=str, default=None, help="Comma-separated listing IDs to review only (e.g. 10576,11038)")
    parser.add_argument("--force", action="store_true", help="Re-run AI review even if listing already has ai_summary (use with --ids)")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            from openai import OpenAI
        except ImportError:
            print("Install openai: pip install openai")
            raise SystemExit(1)
        client = OpenAI(api_key=api_key)
        max_im = getattr(args, "max_images", None)
        run = lambda item: review_one_openai(item, client, max_images=max_im)
        print("Using OpenAI gpt-4o")
    elif anthropic_key:
        try:
            import anthropic
        except ImportError:
            print("Install anthropic: pip install anthropic")
            raise SystemExit(1)
        client = anthropic.Anthropic(api_key=anthropic_key)
        max_im = getattr(args, "max_images", None)
        run = lambda item: review_one_anthropic(item, client, max_images=max_im)
        print("Using Anthropic Claude")
    else:
        print("Set OPENAI_API_KEY or ANTHROPIC_API_KEY and re-run.")
        raise SystemExit(1)
    path = args.input
    if not path.exists():
        print(f"File not found: {path}")
        raise SystemExit(1)

    with open(path, "r", encoding="utf-8") as f:
        listings = json.load(f)

    if not isinstance(listings, list):
        print("Expected a JSON array of listings")
        raise SystemExit(1)

    skip_done = args.skip_done and not getattr(args, "force", False)
    to_do = [
        L
        for L in listings
        if isinstance(L, dict)
        and (not skip_done or not (L.get("ai_summary") or (L.get("ai_score") is not None)))
    ]
    if getattr(args, "ids", None):
        id_set = set(int(x.strip()) for x in args.ids.split(",") if x.strip())
        to_do = [L for L in to_do if L.get("id") in id_set]
    if args.limit is not None:
        to_do = to_do[: args.limit]

    total = len(to_do)
    if total == 0:
        print("No listings to review (none left or already have ai_summary).")
        return

    id_to_index = {L["id"]: i for i, L in enumerate(listings)}
    done = 0
    save_every = 1

    if args.parallel <= 1:
        for i, listing in enumerate(to_do, 1):
            print(f"[{i}/{total}] id={listing.get('id')} {listing.get('street') or '?'} ...")
            try:
                updated = run(listing)
                idx = id_to_index.get(updated["id"])
                if idx is not None:
                    listings[idx] = updated
                done += 1
                if done % save_every == 0:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(listings, f, indent=2, ensure_ascii=False)
                    print(f"  -> score={updated.get('ai_score')} saved.")
            except Exception as e:
                print(f"  -> error: {e}")
            time.sleep(0.5)
    else:
        with ThreadPoolExecutor(max_workers=args.parallel) as ex:
            futures = {ex.submit(run, L): L for L in to_do}
            for i, fut in enumerate(as_completed(futures), 1):
                listing = futures[fut]
                try:
                    updated = fut.result()
                    idx = id_to_index.get(updated["id"])
                    if idx is not None:
                        listings[idx] = updated
                    done += 1
                    print(f"[{i}/{total}] id={updated.get('id')} score={updated.get('ai_score')}")
                    if done % save_every == 0:
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(listings, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"[{i}/{total}] id={listing.get('id')} error: {e}")
            time.sleep(0.1)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)
    print(f"Done. Reviewed {done} listings, saved to {path}")
    if args.copy_frontend and path.resolve() != Path("frontend/public/data/listings.json").resolve():
        front = Path("frontend/public/data/listings.json")
        front.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(path, front)
        print(f"Copied to {front}")


if __name__ == "__main__":
    main()
