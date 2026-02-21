import "./styles/index.css";

import { DEFAULT_CENTER } from "./config";
import { normalizeListing } from "./converters";
import { applyFilters, readFilters, writeFilters, type FilterContext } from "./filters";
import { hasDislike, onDislikesChange, seedDefaultsIfEmpty as seedDislikesIfEmpty } from "./dislikes";
import { formatFavoritesForClipboard, getFavorites, hasFavorite, onFavoritesChange, seedDefaultsIfEmpty } from "./favorites";
import { GalleryController } from "./gallery";
import { buildWalkingMinutesIndex } from "./geo";
import { readHash, writeHash, writeHashDebounced, type HashState } from "./hashState";
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
  let selectedId: number | undefined = hash.selectedId;

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
    onFocusListing: (id) => {
      selectedId = id == null ? undefined : id;
      syncHashNow();
    },
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
  const favoritesOnlyToggle = document.getElementById("favoritesOnly") as HTMLInputElement | null;
  const hideDislikedToggle = document.getElementById("hideDisliked") as HTMLInputElement | null;
  const tableToggle = document.getElementById("tableToggle") as HTMLInputElement | null;

  if (hash.greens != null && greensToggle) greensToggle.checked = hash.greens;
  if (hash.rings != null && ringsToggle) ringsToggle.checked = hash.rings;
  if (hash.favoritesOnly != null && favoritesOnlyToggle) favoritesOnlyToggle.checked = hash.favoritesOnly;
  if (hash.hideDisliked != null && hideDislikedToggle) hideDislikedToggle.checked = hash.hideDisliked;
  if (hash.table != null && tableToggle) tableToggle.checked = hash.table;

  // --- Overlays -----------------------------------------------------------

  const filterCtx: FilterContext = { walkingIndex: null };

  try {
    const greens = await fetchJson<GeoJSON.FeatureCollection>(`${base}data/greens.geojson`);
    map.setGreens(greens);
    if (greensToggle && !greensToggle.checked) map.setGreensVisible(false);
    greensToggle?.addEventListener("change", () => {
      map.setGreensVisible(greensToggle.checked);
      syncHashNow();
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
      syncHashNow();
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

  // --- Filters (restore from hash if present) -------------------------------

  if (hash.filters) writeFilters(hash.filters);

  // --- Table toggle -------------------------------------------------------

  const tableVisible = tableToggle?.checked ?? false;
  document.body.classList.toggle("table-hidden", !tableVisible);

  if (favoritesOnlyToggle) {
    favoritesOnlyToggle.addEventListener("change", () => {
      renderFromUi();
      syncHashNow();
    });
  }

  if (hideDislikedToggle) {
    hideDislikedToggle.addEventListener("change", () => {
      renderFromUi();
      syncHashNow();
    });
  }

  if (tableToggle) {
    tableToggle.addEventListener("change", () => {
      document.body.classList.toggle("table-hidden", !tableToggle.checked);
      window.setTimeout(() => map.invalidateSize(), 50);
      syncHashNow();
    });
  }

  const table = new TableController({
    onRowClick: (l) => {
      map.setView(l.lat, l.lng, 16);
      map.zoomToListing(l.id);
    },
    openGallery: (p) => gallery.open(p),
  });

  // Re-apply view when favorites/dislikes change and the corresponding filter is on.
  // (onFavoritesChange/onDislikesChange invoke listeners immediately, so register only after controllers exist.)
  onFavoritesChange(() => {
    if (favoritesOnlyToggle?.checked) renderFromUi();
  });

  onDislikesChange(() => {
    if (hideDislikedToggle?.checked) renderFromUi();
  });

  // --- Render helpers -----------------------------------------------------

  function updateView(filtered: Listing[], opts?: { fit?: boolean }): void {
    map.render(filtered);
    if (opts?.fit) map.fitToListings(filtered);
    table.setListings(filtered);
  }

  function renderFromUi(): void {
    let filtered = applyFilters(listings, readFilters(), filterCtx);
    if (favoritesOnlyToggle?.checked) filtered = filtered.filter((l) => hasFavorite(l.url));
    if (hideDislikedToggle?.checked) filtered = filtered.filter((l) => !hasDislike(l.url));
    updateView(filtered);
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
      favoritesOnly: favoritesOnlyToggle?.checked,
      hideDisliked: hideDislikedToggle?.checked,
      selectedId,
    };
  }

  function syncHash(): void {
    writeHashDebounced(buildCurrentHash());
  }

  function syncHashNow(): void {
    writeHash(buildCurrentHash());
  }

  map.onMoveEnd(syncHash);

  // --- Live filtering -----------------------------------------------------

  const liveIds = ["minPrice", "maxPrice", "minArea", "aiScoreFilter", "walkFilter"];
  for (const id of liveIds) {
    const el = document.getElementById(id);
    if (!el) continue;
    // Prefer "input" for live updates; for <select>, also listen to "change" for compatibility.
    if (el instanceof HTMLSelectElement) {
      el.addEventListener("input", renderFromUi);
      el.addEventListener("change", renderFromUi);
    } else {
      el.addEventListener("input", renderFromUi);
    }
  }

  // --- Initial render -----------------------------------------------------

  (function doInitialRender() {
    let filtered = applyFilters(listings, readFilters(), filterCtx);
    if (favoritesOnlyToggle?.checked) filtered = filtered.filter((l) => hasFavorite(l.url));
    if (hideDislikedToggle?.checked) filtered = filtered.filter((l) => !hasDislike(l.url));
    updateView(filtered, { fit: !hasMapView });
    if (selectedId != null) map.zoomToListing(selectedId);
  })();
  syncHash();
}

boot().catch((err: unknown) => {
  console.error("App failed to start:", err);
});
