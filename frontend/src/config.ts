import type { LatLng } from "./types";

export const DEFAULT_CENTER: LatLng = { lat: 40.1862324, lng: 44.5047339 };

export const PRICE_BRACKETS = [
  { max: 2500, color: "#2ecc71", label: "low" },
  { max: 3500, color: "#3498db", label: "mid1" },
  { max: 4200, color: "#f39c12", label: "mid2" },
  { max: Infinity, color: "#e74c3c", label: "high" },
] as const;

export const UNKNOWN_PRICE_COLOR = "#808080";

export function priceColor(price: number | null): string {
  if (price == null) return UNKNOWN_PRICE_COLOR;
  for (const bracket of PRICE_BRACKETS) {
    if (price <= bracket.max) return bracket.color;
  }
  return UNKNOWN_PRICE_COLOR;
}
