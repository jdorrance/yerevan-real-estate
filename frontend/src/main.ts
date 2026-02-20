import "./styles/index.css";

import { DEFAULT_EU } from "./config";
import { normalizeListing } from "./converters";
import { applyFilters, initDistrictFilter, readFilters, setWalkingMinutesIndex } from "./filters";
import { GalleryController } from "./gallery";
import { MapController } from "./map";
import { TableController } from "./table";
import type { AppConfig, Listing, ListingRaw } from "./types";

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
  return res.json() as Promise<T>;
}

async function loadConfig(base: string): Promise<AppConfig> {
  try {
    return await fetchJson<AppConfig>(`${base}data/config.json`);
  } catch {
    return { eu: DEFAULT_EU };
  }
}

async function boot(): Promise<void> {
  const base = import.meta.env.BASE_URL;

  const [config, rawListings] = await Promise.all([
    loadConfig(base),
    fetchJson<ListingRaw[]>(`${base}data/listings.json`),
  ]);

  const listings: Listing[] = rawListings
    .map(normalizeListing)
    .filter((l): l is Listing => l != null);

  const eu = config.eu ?? DEFAULT_EU;
  const gallery = new GalleryController();
  const map = new MapController({ eu, openGallery: (p) => gallery.open(p) });

  // Optional overlay: walking time isochrones (committed as a static GeoJSON file).
  try {
    const isochrones = await fetchJson<GeoJSON.FeatureCollection>(`${base}data/isochrones.geojson`);
    map.setWalkingIsochrones(isochrones);
    setWalkingMinutesIndex(buildWalkingMinutesIndex(listings, isochrones));
  } catch {
    // If the file isn't present (or network blocked), the overlay is simply omitted.
    setWalkingMinutesIndex(null);
  }

  initDistrictFilter(listings);

  const table = new TableController({
    onRowClick: (l) => {
      map.setView(l.lat, l.lng, 16);
      map.zoomToListing(l.id);
    },
    openGallery: (p) => gallery.open(p),
  });

  const statsEl = document.getElementById("stats");

  function updateView(filtered: Listing[]): void {
    map.render(filtered);
    map.fitToListings(filtered);
    table.setListings(filtered);
    if (statsEl) {
      statsEl.textContent = `${filtered.length} listings shown of ${listings.length} total`;
    }
  }

  document.getElementById("applyFilters")?.addEventListener("click", () => {
    updateView(applyFilters(listings, readFilters()));
  });

  updateView(listings);
}

boot().catch((err: unknown) => {
  console.error("App failed to start:", err);
  const el = document.getElementById("stats");
  if (el) el.textContent = "Failed to start app (see console)";
});

type Ring = Array<[lng: number, lat: number]>;

function pointInRing(lng: number, lat: number, ring: Ring): boolean {
  // Ray casting. Ring is [lng,lat] points.
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    const intersect = (yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi + 0.0) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function extractOuterRings(geometry: GeoJSON.Geometry): Ring[] {
  if (geometry.type === "Polygon") {
    const coords = geometry.coordinates?.[0] ?? [];
    return [coords.map((p) => [p[0] as number, p[1] as number])];
  }
  if (geometry.type === "MultiPolygon") {
    return (geometry.coordinates ?? []).map((poly) =>
      (poly?.[0] ?? []).map((p) => [p[0] as number, p[1] as number])
    );
  }
  return [];
}

function buildWalkingMinutesIndex(listings: Listing[], geojson: GeoJSON.FeatureCollection): Map<number, number> {
  const ringsByMinutes = new Map<number, Ring[]>();
  for (const f of geojson.features) {
    if (!f.geometry) continue;
    const seconds = Number((f.properties as any)?.value ?? NaN);
    if (!Number.isFinite(seconds)) continue;
    const minutes = Math.round(seconds / 60);
    if (minutes !== 15 && minutes !== 30) continue;
    const rings = extractOuterRings(f.geometry);
    if (!rings.length) continue;
    ringsByMinutes.set(minutes, rings);
  }

  const rings15 = ringsByMinutes.get(15) ?? [];
  const rings30 = ringsByMinutes.get(30) ?? [];

  const out = new Map<number, number>();
  for (const l of listings) {
    const lng = l.lng;
    const lat = l.lat;

    let minutes: number | null = null;
    if (rings15.some((r) => pointInRing(lng, lat, r))) minutes = 15;
    else if (rings30.some((r) => pointInRing(lng, lat, r))) minutes = 30;

    if (minutes != null) out.set(l.id, minutes);
  }
  return out;
}
