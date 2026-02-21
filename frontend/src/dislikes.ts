type Listener = (urls: ReadonlySet<string>) => void;

const STORAGE_KEY = "yerevan-dislikes";

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
    // ignore
  }
}

function emit(urls: ReadonlySet<string>): void {
  for (const l of listeners) l(urls);
}

export function hasDislike(url: string): boolean {
  if (!url) return false;
  return load().has(url);
}

export function addDislike(url: string): void {
  if (!url) return;
  const s = load();
  if (s.has(url)) return;
  s.add(url);
  persist(s);
  emit(s);
}

export function removeDislike(url: string): void {
  if (!url) return;
  const s = load();
  if (!s.delete(url)) return;
  persist(s);
  emit(s);
}

export function toggleDislike(url: string): boolean {
  if (!url) return false;
  const s = load();
  if (s.has(url)) s.delete(url);
  else s.add(url);
  persist(s);
  emit(s);
  return s.has(url);
}

export function getDislikes(): ReadonlySet<string> {
  return load();
}

/** If the user has no dislikes in localStorage, seed with default URLs and persist. */
export function seedDefaultsIfEmpty(defaultUrls: string[]): void {
  const urls = defaultUrls.filter((u) => typeof u === "string" && u.length > 0);
  if (urls.length === 0) return;
  const current = load();
  if (current.size > 0) return;
  for (const u of urls) current.add(u);
  cache = current;
  persist(current);
  emit(current);
}

export function onDislikesChange(listener: Listener): () => void {
  listeners.add(listener);
  listener(load());
  return () => listeners.delete(listener);
}

