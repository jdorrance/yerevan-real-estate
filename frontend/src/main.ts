import "./styles/index.css";

import { DEFAULT_CENTER } from "./config";
import { normalizeListing } from "./converters";
import { applyFilters, initDistrictFilter, readFilters, writeFilters, type FilterContext } from "./filters";
import { seedDefaultsIfEmpty as seedDislikesIfEmpty } from "./dislikes";
import { formatFavoritesForClipboard, getFavorites, onFavoritesChange, seedDefaultsIfEmpty } from "./favorites";
import { GalleryController } from "./gallery";
import { buildWalkingMinutesIndex } from "./geo";
import { readHash, writeHashDebounced, type HashState } from "./hashState";
import { MapController } from "./map";
import { TableController } from "./table";
import type { AppConfig, Listing, ListingRaw } from "./types";

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
  return res.json() as Promise<T>;
}

async function loadConfig(base: string): Promise<AppConfig> {
  try {
    return await fetchJson<AppConfig>(`${base}data/config.json`);
  } catch {
    return {};
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot(): Promise<void> {
  const base = import.meta.env.BASE_URL;
  const hash = readHash();

  const [config, rawListings, shortlistUrls, defaultDislikes] = await Promise.all([
    loadConfig(base),
    fetchJson<ListingRaw[]>(`${base}data/listings.json`),
    fetchJson<string[]>(`${base}data/shortlist.json`).catch(() => []),
    fetchJson<string[]>(`${base}data/dislikes.json`).catch(() => []),
  ]);

  seedDefaultsIfEmpty(Array.isArray(shortlistUrls) ? shortlistUrls : []);
  seedDislikesIfEmpty(Array.isArray(defaultDislikes) ? defaultDislikes : []);

  const listings: Listing[] = rawListings
    .map(normalizeListing)
    .filter((l): l is Listing => l != null);

  const center = config.center ?? config.eu ?? DEFAULT_CENTER;
  const hasMapView = hash.zoom != null && hash.lat != null && hash.lng != null;

  // --- Controllers --------------------------------------------------------

  const gallery = new GalleryController();
  const map = new MapController({
    center,
    initialView: hasMapView ? { lat: hash.lat!, lng: hash.lng!, zoom: hash.zoom! } : undefined,
    openGallery: (p) => gallery.open(p),
    preloadPhotos: (p) => void gallery.preloadAll(p),
  });

  // --- Favorites export ---------------------------------------------------
  const exportBtn = document.getElementById("exportFavs") as HTMLButtonElement | null;
  if (exportBtn) {
    const update = (urls: ReadonlySet<string>) => {
      exportBtn.textContent = `★ ${urls.size} — Copy`;
    };
    onFavoritesChange(update);

    exportBtn.addEventListener("click", async () => {
      const text = formatFavoritesForClipboard(listings);
      if (!text) {
        exportBtn.textContent = "No favorites";
        window.setTimeout(() => update(getFavorites()), 900);
        return;
      }

      const original = exportBtn.textContent;
      try {
        await navigator.clipboard.writeText(text);
        exportBtn.textContent = "Copied!";
      } catch {
        // Fallback for stricter browser contexts (best-effort).
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand("copy");
          exportBtn.textContent = "Copied!";
        } catch {
          exportBtn.textContent = "Copy failed";
        } finally {
          document.body.removeChild(ta);
        }
      } finally {
        window.setTimeout(() => {
          if (original) exportBtn.textContent = original;
        }, 1100);
      }
    });
  }

  // --- Toggle checkboxes --------------------------------------------------

  const greensToggle = document.getElementById("greensToggle") as HTMLInputElement | null;
  const ringsToggle = document.getElementById("ringsToggle") as HTMLInputElement | null;
  const tableToggle = document.getElementById("tableToggle") as HTMLInputElement | null;

  if (hash.greens != null && greensToggle) greensToggle.checked = hash.greens;
  if (hash.rings != null && ringsToggle) ringsToggle.checked = hash.rings;
  if (hash.table != null && tableToggle) tableToggle.checked = hash.table;

  // --- Overlays -----------------------------------------------------------

  const filterCtx: FilterContext = { walkingIndex: null };

  try {
    const greens = await fetchJson<GeoJSON.FeatureCollection>(`${base}data/greens.geojson`);
    map.setGreens(greens);
    if (greensToggle && !greensToggle.checked) map.setGreensVisible(false);
    greensToggle?.addEventListener("change", () => {
      map.setGreensVisible(greensToggle.checked);
      syncHash();
    });
  } catch {
    // Greens file absent — silently skip.
  }

  try {
    const isochrones = await fetchJson<GeoJSON.FeatureCollection>(`${base}data/isochrones.geojson`);
    map.setWalkingIsochrones(isochrones);
    if (ringsToggle && !ringsToggle.checked) map.setWalkingIsochronesVisible(false);
    filterCtx.walkingIndex = buildWalkingMinutesIndex(listings, isochrones);
    ringsToggle?.addEventListener("change", () => {
      map.setWalkingIsochronesVisible(ringsToggle.checked);
      syncHash();
    });
  } catch {
    if (ringsToggle) {
      ringsToggle.checked = false;
      ringsToggle.disabled = true;
    }
  }

  // Disable walk filter dropdown when no isochrone data is available.
  const walkSelect = document.getElementById("walkFilter") as HTMLSelectElement | null;
  if (walkSelect) walkSelect.disabled = filterCtx.walkingIndex == null;

  // --- Filters (district options first so hash values can be applied) ------

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
    updateView(applyFilters(listings, readFilters(), filterCtx));
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

  map.onMoveEnd(syncHash);

  // --- Live filtering -----------------------------------------------------

  const liveIds = ["minPrice", "maxPrice", "minArea", "minRooms", "distFilter", "walkFilter"];
  for (const id of liveIds) {
    const el = document.getElementById(id);
    if (!el) continue;
    const evt = el instanceof HTMLInputElement ? "input" : "change";
    el.addEventListener(evt, renderFromUi);
  }

  // --- Initial render -----------------------------------------------------

  updateView(applyFilters(listings, readFilters(), filterCtx), { fit: !hasMapView });
  syncHash();
}

boot().catch((err: unknown) => {
  console.error("App failed to start:", err);
});
