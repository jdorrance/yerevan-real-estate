import type { FilterValues } from "./types";

export interface HashState {
  zoom?: number;
  lat?: number;
  lng?: number;
  filters?: Partial<FilterValues>;
  greens?: boolean;
  rings?: boolean;
  table?: boolean;
  favoritesOnly?: boolean;
  hideDisliked?: boolean;
}

/**
 * Hash format:  #z/lat/lng?key=val&key=val
 * Map portion is optional; if absent the app uses its default view.
 */
export function readHash(): HashState {
  const raw = location.hash.replace(/^#/, "");
  if (!raw) return {};

  const [pathPart, queryPart] = splitOnce(raw, "?");
  const state: HashState = {};

  if (pathPart) {
    const [zStr, latStr, lngStr] = pathPart.split("/");
    const z = Number(zStr);
    const lat = Number(latStr);
    const lng = Number(lngStr);
    if (Number.isFinite(z) && Number.isFinite(lat) && Number.isFinite(lng)) {
      state.zoom = z;
      state.lat = lat;
      state.lng = lng;
    }
  }

  if (queryPart) {
    const params = new URLSearchParams(queryPart);
    const filters: Partial<FilterValues> = {};

    const minPrice = safeNum(params.get("minPrice"));
    const maxPrice = safeNum(params.get("maxPrice"));
    const minArea = safeNum(params.get("minArea"));
    const minAiScore = safeNum(params.get("aiScore"));
    const walkMaxMinutes = safeNum(params.get("walk"));

    if (minPrice != null) filters.minPrice = minPrice;
    if (maxPrice != null) filters.maxPrice = maxPrice;
    if (minArea != null) filters.minArea = minArea;
    if (minAiScore != null) filters.minAiScore = minAiScore;
    if (walkMaxMinutes != null) filters.walkMaxMinutes = walkMaxMinutes;

    if (Object.keys(filters).length) state.filters = filters;

    if (params.has("greens")) state.greens = params.get("greens") === "1";
    if (params.has("rings")) state.rings = params.get("rings") === "1";
    if (params.has("table")) state.table = params.get("table") === "1";
    if (params.has("fav")) state.favoritesOnly = params.get("fav") === "1";
    if (params.has("hide")) state.hideDisliked = params.get("hide") === "1";
  }

  return state;
}

export function writeHash(state: HashState): void {
  const mapPart =
    state.zoom != null && state.lat != null && state.lng != null
      ? `${state.zoom}/${round6(state.lat)}/${round6(state.lng)}`
      : "";

  const params = new URLSearchParams();
  const f = state.filters;
  if (f) {
    if (f.minPrice != null) params.set("minPrice", String(f.minPrice));
    if (f.maxPrice != null) params.set("maxPrice", String(f.maxPrice));
    if (f.minArea != null && f.minArea > 0) params.set("minArea", String(f.minArea));
    if (f.minAiScore != null && f.minAiScore > 0) params.set("aiScore", String(f.minAiScore));
    if (f.walkMaxMinutes != null && f.walkMaxMinutes > 0) params.set("walk", String(f.walkMaxMinutes));
  }
  if (state.greens != null) params.set("greens", state.greens ? "1" : "0");
  if (state.rings != null) params.set("rings", state.rings ? "1" : "0");
  if (state.table != null) params.set("table", state.table ? "1" : "0");
  if (state.favoritesOnly != null) params.set("fav", state.favoritesOnly ? "1" : "0");
  if (state.hideDisliked != null) params.set("hide", state.hideDisliked ? "1" : "0");

  const query = params.toString();
  const hash = mapPart + (query ? `?${query}` : "");
  if (hash) {
    history.replaceState(null, "", `#${hash}`);
  } else {
    history.replaceState(null, "", location.pathname + location.search);
  }
}

let pendingTimer: ReturnType<typeof setTimeout> | null = null;

/** Debounced writeHash — coalesces rapid calls (e.g. during map pan). */
export function writeHashDebounced(state: HashState, ms = 150): void {
  if (pendingTimer != null) clearTimeout(pendingTimer);
  pendingTimer = setTimeout(() => {
    pendingTimer = null;
    writeHash(state);
  }, ms);
}

function splitOnce(s: string, sep: string): [string, string] {
  const idx = s.indexOf(sep);
  return idx === -1 ? [s, ""] : [s.slice(0, idx), s.slice(idx + 1)];
}

function safeNum(v: string | null): number | undefined {
  if (v == null) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function round6(v: number): string {
  return v.toFixed(6);
}
