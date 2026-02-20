import type { FilterValues, Listing } from "./types";

export interface FilterContext {
  walkingIndex: ReadonlyMap<number, number> | null;
}

export function initDistrictFilter(listings: readonly Listing[]): void {
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

export function applyFilters(
  all: readonly Listing[],
  filters: FilterValues,
  ctx: FilterContext,
): Listing[] {
  return all.filter((l) => {
    if (l.price != null && (l.price < filters.minPrice || l.price > filters.maxPrice)) return false;
    if (l.area != null && l.area < filters.minArea) return false;
    if (l.rooms != null && l.rooms < filters.minRooms) return false;
    if (filters.district && l.district !== filters.district) return false;
    if (filters.walkMaxMinutes > 0) {
      const minutes = ctx.walkingIndex?.get(l.id);
      if (minutes == null || minutes > filters.walkMaxMinutes) return false;
    }
    return true;
  });
}

/** Restore filter DOM controls from (partial) values — used on boot from URL hash. */
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
