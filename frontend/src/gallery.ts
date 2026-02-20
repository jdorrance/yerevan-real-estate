import { $ } from "./dom";

export class GalleryController {
  private root: HTMLElement;
  private img: HTMLImageElement;
  private counter: HTMLElement;
  private photos: string[] = [];
  private idx = 0;
  private loaded = new Set<string>();
  private inflight = new Map<string, Promise<void>>();
  private onKeyDownCapture: ((e: KeyboardEvent) => void) | null = null;

  constructor() {
    this.root = $("#gallery");
    this.counter = $("#gallery-counter");

    const img = document.getElementById("gallery-img");
    if (!(img instanceof HTMLImageElement)) throw new Error("#gallery-img is not an <img>");
    this.img = img;

    $("#galleryClose").addEventListener("click", () => this.close());
    $("#galleryPrev").addEventListener("click", () => this.nav(-1));
    $("#galleryNext").addEventListener("click", () => this.nav(1));

    this.root.addEventListener("click", (e) => {
      if (e.target === this.root) this.close();
    });
  }

  isOpen(): boolean {
    return this.root.classList.contains("active");
  }

  open(photos: string[]): void {
    if (!photos.length) return;
    this.photos = photos;
    this.idx = 0;
    // Start preloading immediately so next/prev is snappy.
    void this.preloadAll(photos);
    this.show();
    this.root.classList.add("active");
    this.root.setAttribute("aria-hidden", "false");
    this.root.focus?.();
    this.installKeyCapture();
  }

  close(): void {
    this.root.classList.remove("active");
    this.root.setAttribute("aria-hidden", "true");
    this.uninstallKeyCapture();
  }

  private installKeyCapture(): void {
    if (this.onKeyDownCapture) return;
    this.onKeyDownCapture = (e: KeyboardEvent) => {
      if (!this.isOpen()) return;
      // Prevent Leaflet (map keyboard pan) from also handling arrow keys.
      if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        if (e.key === "ArrowLeft") this.nav(-1);
        else if (e.key === "ArrowRight") this.nav(1);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        this.close();
      }
    };

    window.addEventListener("keydown", this.onKeyDownCapture, true);
  }

  private uninstallKeyCapture(): void {
    if (!this.onKeyDownCapture) return;
    window.removeEventListener("keydown", this.onKeyDownCapture, true);
    this.onKeyDownCapture = null;
  }

  private nav(dir: number): void {
    if (!this.photos.length) return;
    this.idx = (this.idx + dir + this.photos.length) % this.photos.length;
    this.show();
  }

  private show(): void {
    this.img.src = this.photos[this.idx] ?? "";
    this.counter.textContent = `${this.idx + 1} / ${this.photos.length}`;
  }

  preloadAll(photos: string[], opts?: { concurrency?: number }): Promise<void> {
    const concurrency = Math.max(1, Math.min(8, opts?.concurrency ?? 4));
    const queue = photos.filter(Boolean);
    let i = 0;

    const worker = async () => {
      while (true) {
        const url = queue[i++];
        if (!url) return;
        await this.preloadUrl(url);
      }
    };

    const workers = Array.from({ length: Math.min(concurrency, queue.length) }, () => worker());
    return Promise.all(workers).then(() => undefined);
  }

  private preloadUrl(url: string): Promise<void> {
    if (this.loaded.has(url)) return Promise.resolve();
    const existing = this.inflight.get(url);
    if (existing) return existing;

    const p = new Promise<void>((resolve) => {
      const img = new Image();
      // Best-effort: warm browser cache. Ignore CORS/load failures.
      img.onload = async () => {
        this.loaded.add(url);
        this.inflight.delete(url);
        try {
          // decode() is optional; helps on some browsers.
          if ("decode" in img && typeof img.decode === "function") await img.decode();
        } catch {
          // ignore
        }
        resolve();
      };
      img.onerror = () => {
        this.inflight.delete(url);
        resolve();
      };
      img.src = url;
    });

    this.inflight.set(url, p);
    return p;
  }
}
