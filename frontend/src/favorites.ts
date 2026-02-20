import type { Listing } from "./types";
import { formatPrice } from "./dom";

const STORAGE_KEY = "yerevan-favorites";

type Listener = (urls: ReadonlySet<string>) => void;

let cache: Set<string> | null = null;
const listeners = new Set<Listener>();

function load(): Set<string> {
  if (cache) return cache;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    const urls = Array.isArray(arr) ? arr.filter((u) => typeof u === "string" && u.length > 0) : [];
    cache = new Set(urls);
  } catch {
    cache = new Set();
  }
  return cache;
}

function persist(urls: ReadonlySet<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...urls]));
  } catch {
    // ignore (quota/private mode)
  }
}

function emit(urls: ReadonlySet<string>): void {
  for (const l of listeners) l(urls);
}

export function hasFavorite(url: string): boolean {
  if (!url) return false;
  return load().has(url);
}

export function toggleFavorite(url: string): boolean {
  if (!url) return false;
  const s = load();
  if (s.has(url)) s.delete(url);
  else s.add(url);
  persist(s);
  emit(s);
  return s.has(url);
}

export function removeFavorite(url: string): void {
  if (!url) return;
  const s = load();
  if (!s.delete(url)) return;
  persist(s);
  emit(s);
}

export function getFavorites(): ReadonlySet<string> {
  return load();
}

export function favoritesCount(): number {
  return load().size;
}

export function onFavoritesChange(listener: Listener): () => void {
  listeners.add(listener);
  // immediate first call for convenience
  listener(load());
  return () => listeners.delete(listener);
}

export function formatFavoritesForClipboard(allListings: readonly Listing[]): string {
  const favs = load();
  const selected = allListings.filter((l) => l.url && favs.has(l.url));
  if (selected.length === 0) return "";

  const lines: string[] = [];
  for (const l of selected) {
    const price = `${formatPrice(l.price)}${l.price != null ? "/mo" : ""}`;
    const street = l.street || "?";
    lines.push(`${street} — ${price} — ${l.url}`);
  }
  return lines.join("\n");
}
