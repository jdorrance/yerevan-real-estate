import "./styles/index.css";

import { DEFAULT_EU } from "./config";
import { normalizeListing } from "./converters";
import { applyFilters, initDistrictFilter, readFilters } from "./filters";
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
