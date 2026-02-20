import { escapeHtml, formatNullable, formatPrice, td, tdHtml } from "./dom";
import { comparePrimitive } from "./sort";
import type { Listing } from "./types";

type SortableKey = "id" | "district" | "street" | "price" | "area" | "land_area" | "rooms" | "floors" | "building_type" | "photo_count";

const SORT_KEYS: readonly SortableKey[] = [
  "id", "district", "street", "price", "area", "land_area", "rooms", "floors", "building_type", "photo_count",
];

interface TableOptions {
  onRowClick: (listing: Listing) => void;
  openGallery: (photos: string[]) => void;
}

export class TableController {
  private tbody: HTMLTableSectionElement;
  private listings: Listing[] = [];
  private sortCol = -1;
  private sortAsc = true;
  private onRowClick: TableOptions["onRowClick"];
  private openGallery: TableOptions["openGallery"];

  constructor({ onRowClick, openGallery }: TableOptions) {
    const tbody = document.getElementById("tbody") as HTMLTableSectionElement | null;
    const thead = document.querySelector<HTMLTableSectionElement>("#listings-table thead");
    if (!tbody || !thead) throw new Error("Table DOM elements not found");

    this.tbody = tbody;
    this.onRowClick = onRowClick;
    this.openGallery = openGallery;

    thead.addEventListener("click", (e) => {
      const th = (e.target as HTMLElement).closest<HTMLTableCellElement>("th[data-col]");
      if (!th) return;
      const col = Number(th.dataset.col);
      if (Number.isFinite(col)) this.toggleSort(col);
    });

    this.tbody.addEventListener("click", (e) => {
      const target = e.target as HTMLElement;

      const photosCell = target.closest<HTMLElement>("[data-action='photos']");
      if (photosCell) {
        e.stopPropagation();
        const listing = this.findById(Number(photosCell.dataset.id));
        if (listing) this.openGallery(listing.photo_urls);
        return;
      }

      const row = target.closest<HTMLTableRowElement>("tr[data-id]");
      if (!row) return;
      const listing = this.findById(Number(row.dataset.id));
      if (listing) this.onRowClick(listing);
    });
  }

  setListings(listings: Listing[]): void {
    this.listings = [...listings];
    if (this.sortCol >= 0) this.applySort();
    this.renderRows();
  }

  private findById(id: number): Listing | undefined {
    return this.listings.find((l) => l.id === id);
  }

  private toggleSort(col: number): void {
    this.sortAsc = this.sortCol === col ? !this.sortAsc : true;
    this.sortCol = col;
    this.applySort();
    this.renderRows();
  }

  private applySort(): void {
    const key = SORT_KEYS[this.sortCol];
    if (!key) return;
    const asc = this.sortAsc;
    this.listings.sort((a, b) => comparePrimitive(a[key], b[key], asc));
  }

  private renderRows(): void {
    this.tbody.textContent = "";

    for (const l of this.listings) {
      const tr = document.createElement("tr");
      tr.dataset.id = String(l.id);

      tr.append(
        td(String(l.id)),
        td(l.district),
        td(l.street),
        td(formatPrice(l.price)),
        td(formatNullable(l.area)),
        td(formatNullable(l.land_area)),
        td(formatNullable(l.rooms)),
        td(formatNullable(l.floors)),
        td(l.building_type),
        this.createPhotosCell(l),
        this.createLinkCell(l),
      );

      this.tbody.appendChild(tr);
    }
  }

  private createPhotosCell(l: Listing): HTMLTableCellElement {
    const cell = document.createElement("td");
    cell.dataset.action = "photos";
    cell.dataset.id = String(l.id);
    cell.className = "photos-cell";
    cell.textContent = `${l.photo_count} 📷`;
    return cell;
  }

  private createLinkCell(l: Listing): HTMLTableCellElement {
    if (!l.url) return td("");
    return tdHtml(`<a href="${escapeHtml(l.url)}" target="_blank" rel="noreferrer">View</a>`);
  }
}
