import type { FilterValues, Listing } from "./types";

let walkingMinutesById: ReadonlyMap<number, number> | null = null;

export function setWalkingMinutesIndex(index: ReadonlyMap<number, number> | null): void {
  walkingMinutesById = index;
  const select = document.getElementById("walkFilter") as HTMLSelectElement | null;
  if (!select) return;
  select.disabled = !walkingMinutesById;
}

export function initDistrictFilter(listings: Listing[]): void {
  const select = document.getElementById("distFilter") as HTMLSelectElement | null;
  if (!select) throw new Error("District filter <select> not found");

  select.querySelectorAll("option:not([value=''])").forEach((o) => o.remove());

  const districts = [...new Set(listings.map((l) => l.district).filter(Boolean))].sort();
  for (const d of districts) {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d;
    select.appendChild(opt);
  }
}

export function readFilters(): FilterValues {
  return {
    minPrice: readNumber("minPrice", 0),
    maxPrice: readNumber("maxPrice", 99999),
    minArea: readNumber("minArea", 0),
    minRooms: readNumber("minRooms", 0),
    district: (document.getElementById("distFilter") as HTMLSelectElement | null)?.value ?? "",
    walkMaxMinutes: readNumber("walkFilter", 0),
  };
}

export function applyFilters(all: Listing[], f: FilterValues): Listing[] {
  return all.filter((l) => {
    if (l.price != null && (l.price < f.minPrice || l.price > f.maxPrice)) return false;
    if (l.area != null && l.area < f.minArea) return false;
    if (l.rooms != null && l.rooms < f.minRooms) return false;
    if (f.district && l.district !== f.district) return false;
    if (f.walkMaxMinutes > 0) {
      const minutes = walkingMinutesById?.get(l.id);
      if (minutes == null || minutes > f.walkMaxMinutes) return false;
    }
    return true;
  });
}

/** Restore filter DOM controls from (partial) values — used to apply URL hash state on boot. */
export function writeFilters(values: Partial<FilterValues>): void {
  if (values.minPrice != null) setInputValue("minPrice", values.minPrice);
  if (values.maxPrice != null) setInputValue("maxPrice", values.maxPrice);
  if (values.minArea != null) setInputValue("minArea", values.minArea);
  if (values.minRooms != null) setInputValue("minRooms", values.minRooms);
  if (values.district != null) {
    const sel = document.getElementById("distFilter") as HTMLSelectElement | null;
    if (sel) sel.value = values.district;
  }
  if (values.walkMaxMinutes != null) {
    const sel = document.getElementById("walkFilter") as HTMLSelectElement | null;
    if (sel) sel.value = String(values.walkMaxMinutes);
  }
}

function setInputValue(id: string, value: number): void {
  const el = document.getElementById(id) as HTMLInputElement | null;
  if (el) el.value = String(value);
}

function readNumber(id: string, fallback: number): number {
  const el = document.getElementById(id) as HTMLInputElement | null;
  if (!el) return fallback;
  const n = Number(el.value);
  return Number.isFinite(n) ? n : fallback;
}
