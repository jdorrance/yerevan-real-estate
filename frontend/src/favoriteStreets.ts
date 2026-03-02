/**
 * Favorite streets — highlight listings on preferred streets on the map.
 * Street names are matched flexibly (case-insensitive, St/Street normalized).
 */

const STORAGE_KEY = "yerevan-favorite-streets";

let cache: Set<string> | null = null;

function load(): Set<string> {
  if (cache) return cache;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    const names = Array.isArray(arr)
      ? arr.filter((s): s is string => typeof s === "string" && s.trim().length > 0)
      : [];
    cache = new Set(names.map(normalizeForMatch));
  } catch {
    cache = new Set();
  }
  return cache;
}

function persist(names: ReadonlySet<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...names]));
  } catch {
    // ignore
  }
  cache = null;
}

/** Normalize street name for matching: lowercase, collapse St/Street, strip extra whitespace. */
function normalizeForMatch(s: string): string {
  return (s || "")
    .toLowerCase()
    .replace(/\bst\.?\s*$/i, " street")
    .replace(/\bstr\.?\s*$/i, " street")
    .replace(/\s+/g, " ")
    .trim();
}

export function isFavoriteStreet(street: string | null | undefined): boolean {
  if (!street || !street.trim()) return false;
  const normalized = normalizeForMatch(street);
  if (!normalized) return false;
  const favorites = load();
  for (const fav of favorites) {
    if (normalized === fav || normalized.includes(fav) || fav.includes(normalized)) return true;
  }
  return false;
}

export function getFavoriteStreets(): ReadonlySet<string> {
  const raw = localStorage.getItem(STORAGE_KEY);
  const arr = raw ? (JSON.parse(raw) as unknown) : [];
  const names = Array.isArray(arr)
    ? arr.filter((s): s is string => typeof s === "string" && s.trim().length > 0)
    : [];
  return new Set(names);
}

export function addFavoriteStreet(name: string): void {
  const trimmed = (name || "").trim();
  if (!trimmed) return;
  const raw = localStorage.getItem(STORAGE_KEY);
  const arr = raw ? (JSON.parse(raw) as unknown) : [];
  const names = Array.isArray(arr)
    ? arr.filter((s): s is string => typeof s === "string" && s.trim().length > 0)
    : [];
  if (names.includes(trimmed)) return;
  names.push(trimmed);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(names));
  cache = null;
}

export function removeFavoriteStreet(name: string): void {
  const raw = localStorage.getItem(STORAGE_KEY);
  const arr = raw ? (JSON.parse(raw) as unknown) : [];
  const names = Array.isArray(arr)
    ? arr.filter((s): s is string => typeof s === "string" && s.trim().length > 0)
    : [];
  const filtered = names.filter((s) => s.trim().toLowerCase() !== (name || "").trim().toLowerCase());
  if (filtered.length === names.length) return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
  cache = null;
}

/** Seed default favorite streets when localStorage is empty. */
export function seedDefaultsIfEmpty(defaultNames: string[]): void {
  const names = defaultNames.filter((s) => typeof s === "string" && s.trim().length > 0);
  if (names.length === 0) return;
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw && raw !== "[]") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(names));
  cache = null;
}
