import type { Listing, ListingRaw } from "./types";

export function toNumber(value: number | string | null | undefined): number | null {
  if (value == null) return null;
  const n = typeof value === "number" ? value : Number(String(value).trim());
  return Number.isFinite(n) ? n : null;
}

export function toStringArray(value: string[] | string | null | undefined): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value.filter((v) => typeof v === "string" && v.trim().length > 0);
  return String(value).split(";").map((s) => s.trim()).filter(Boolean);
}

export function normalizeListing(raw: ListingRaw): Listing | null {
  const lat = toNumber(raw.lat);
  const lng = toNumber(raw.lng);
  if (lat == null || lng == null) return null;

  const photo_urls = Array.isArray(raw.photo_urls) ? raw.photo_urls : toStringArray(raw.photo_urls);

  return {
    id: raw.id,
    source: raw.source ?? "besthouse",
    url: raw.url ?? "",
    lat,
    lng,
    price: toNumber(raw.price_usd),
    area: toNumber(raw.building_area_sqm),
    land_area: toNumber(raw.land_area_sqm),
    rooms: toNumber(raw.rooms),
    bathrooms: toNumber(raw.bathrooms),
    ceiling_height: toNumber(raw.ceiling_height_m),
    floors: toNumber(raw.floors),
    street: raw.street ?? "",
    district: raw.district ?? "",
    building_type: raw.building_type ?? "",
    condition: raw.condition ?? "",
    precision: raw.geocode_precision ?? "",
    facilities: toStringArray(raw.facilities),
    amenities: toStringArray(raw.amenities),
    description: raw.description ?? "",
    photo_urls,
    photo_count: toNumber(raw.photo_count) ?? photo_urls.length,
    ai_summary: raw.ai_summary ?? "",
    ai_score: toNumber(raw.ai_score),
    resolved_address: raw.resolved_address ?? "",
    resolved_address_confidence: raw.resolved_address_confidence ?? "",
    listed_date: raw.listed_date ?? "",
    renewed_date: raw.renewed_date ?? "",
  };
}
