import { $ } from "./dom";

export class GalleryController {
  private root: HTMLElement;
  private img: HTMLImageElement;
  private counter: HTMLElement;
  private photos: string[] = [];
  private idx = 0;

  constructor() {
    this.root = $("#gallery");
    this.counter = $("#gallery-counter");

    const img = document.getElementById("gallery-img");
    if (!(img instanceof HTMLImageElement)) throw new Error("#gallery-img is not an <img>");
    this.img = img;

    $("#galleryClose").addEventListener("click", () => this.close());
    $("#galleryPrev").addEventListener("click", () => this.nav(-1));
    $("#galleryNext").addEventListener("click", () => this.nav(1));

    document.addEventListener("keydown", (e) => {
      if (!this.isOpen()) return;
      switch (e.key) {
        case "Escape": this.close(); break;
        case "ArrowLeft": this.nav(-1); break;
        case "ArrowRight": this.nav(1); break;
      }
    });

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
    this.show();
    this.root.classList.add("active");
    this.root.setAttribute("aria-hidden", "false");
  }

  close(): void {
    this.root.classList.remove("active");
    this.root.setAttribute("aria-hidden", "true");
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
}
