import "./styles/index.css";

import { DEFAULT_EU } from "./config";
import { normalizeListing } from "./converters";
import { applyFilters, initDistrictFilter, readFilters, setWalkingMinutesIndex, writeFilters } from "./filters";
import { GalleryController } from "./gallery";
import { readHash, writeHashDebounced, type HashState } from "./hashState";
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
  const hash = readHash();

  const [config, rawListings] = await Promise.all([
    loadConfig(base),
    fetchJson<ListingRaw[]>(`${base}data/listings.json`),
  ]);

  const listings: Listing[] = rawListings
    .map(normalizeListing)
    .filter((l): l is Listing => l != null);

  const eu = config.eu ?? DEFAULT_EU;
  const hasMapView = hash.zoom != null && hash.lat != null && hash.lng != null;

  const gallery = new GalleryController();
  const map = new MapController({
    eu,
    initialView: hasMapView ? { lat: hash.lat!, lng: hash.lng!, zoom: hash.zoom! } : undefined,
    openGallery: (p) => gallery.open(p),
    preloadPhotos: (p: string[]) => void gallery.preloadAll(p),
  });

  // --- Toggle checkboxes -------------------------------------------------
  const greensToggle = document.getElementById("greensToggle") as HTMLInputElement | null;
  const ringsToggle = document.getElementById("ringsToggle") as HTMLInputElement | null;
  const tableToggle = document.getElementById("tableToggle") as HTMLInputElement | null;

  // Restore toggle state from hash (if present), otherwise keep DOM defaults.
  if (hash.greens != null && greensToggle) greensToggle.checked = hash.greens;
  if (hash.rings != null && ringsToggle) ringsToggle.checked = hash.rings;
  if (hash.table != null && tableToggle) tableToggle.checked = hash.table;

  // --- Overlays -----------------------------------------------------------
  try {
    const greens = await fetchJson<GeoJSON.FeatureCollection>(`${base}data/greens.geojson`);
    map.setGreens(greens);
    if (greensToggle && !greensToggle.checked) map.setGreensVisible(false);
    greensToggle?.addEventListener("change", () => {
      map.setGreensVisible(greensToggle.checked);
      syncHash();
    });
  } catch {
    // No greens overlay.
  }

  try {
    const isochrones = await fetchJson<GeoJSON.FeatureCollection>(`${base}data/isochrones.geojson`);
    map.setWalkingIsochrones(isochrones);
    if (ringsToggle && !ringsToggle.checked) map.setWalkingIsochronesVisible(false);
    setWalkingMinutesIndex(buildWalkingMinutesIndex(listings, isochrones));
    ringsToggle?.addEventListener("change", () => {
      map.setWalkingIsochronesVisible(ringsToggle.checked);
      syncHash();
    });
  } catch {
    setWalkingMinutesIndex(null);
    if (ringsToggle) {
      ringsToggle.checked = false;
      ringsToggle.disabled = true;
    }
  }

  // --- Filters (district options populated first so hash value can be set) -
  initDistrictFilter(listings);
  if (hash.filters) writeFilters(hash.filters);

  // --- Table toggle -------------------------------------------------------
  const tableVisible = tableToggle?.checked ?? false;
  document.body.classList.toggle("table-hidden", !tableVisible);
  if (tableToggle) {
    tableToggle.addEventListener("change", () => {
      document.body.classList.toggle("table-hidden", !tableToggle.checked);
      window.setTimeout(() => map.invalidateSize(), 50);
      syncHash();
    });
  }

  const table = new TableController({
    onRowClick: (l) => {
      map.setView(l.lat, l.lng, 16);
      map.zoomToListing(l.id);
    },
    openGallery: (p) => gallery.open(p),
  });

  // --- Render helpers -----------------------------------------------------
  function updateView(filtered: Listing[], opts?: { fit?: boolean }): void {
    map.render(filtered);
    if (opts?.fit) map.fitToListings(filtered);
    table.setListings(filtered);
  }

  function renderFromUi(): void {
    updateView(applyFilters(listings, readFilters()));
    syncHash();
  }

  // --- Hash sync ----------------------------------------------------------
  function buildCurrentHash(): HashState {
    const view = map.getView();
    return {
      zoom: view.zoom,
      lat: view.lat,
      lng: view.lng,
      filters: readFilters(),
      greens: greensToggle?.checked,
      rings: ringsToggle?.checked,
      table: tableToggle?.checked,
    };
  }

  function syncHash(): void {
    writeHashDebounced(buildCurrentHash());
  }

  // Keep hash in sync with map pan/zoom.
  map.onMoveEnd(() => syncHash());

  // --- Live filtering + button --------------------------------------------
  document.getElementById("applyFilters")?.addEventListener("click", renderFromUi);

  const liveIds = ["minPrice", "maxPrice", "minArea", "minRooms", "distFilter", "walkFilter"];
  for (const id of liveIds) {
    const el = document.getElementById(id);
    if (!el) continue;
    const evt = el instanceof HTMLInputElement ? "input" : "change";
    el.addEventListener(evt, renderFromUi);
  }

  // --- Initial render -----------------------------------------------------
  updateView(applyFilters(listings, readFilters()), { fit: !hasMapView });
  syncHash();
}

boot().catch((err: unknown) => {
  console.error("App failed to start:", err);
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
