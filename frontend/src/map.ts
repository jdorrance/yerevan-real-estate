import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";

import { priceColor } from "./config";
import { escapeHtml, formatNullable, formatPrice } from "./dom";
import type { Listing } from "./types";

export type OpenGalleryFn = (photos: string[]) => void;

interface MapOptions {
  eu: { lat: number; lng: number };
  openGallery: OpenGalleryFn;
}

const CLUSTER_SIZES = { small: 28, medium: 36, large: 44 } as const;

function clusterSize(count: number): keyof typeof CLUSTER_SIZES {
  if (count >= 20) return "large";
  if (count >= 5) return "medium";
  return "small";
}

function createClusterIcon(cluster: L.MarkerCluster): L.DivIcon {
  const count = cluster.getChildCount();
  const size = clusterSize(count);
  const px = CLUSTER_SIZES[size];
  const fontSize = size === "large" ? 14 : 12;
  return L.divIcon({
    html: `<div class="cluster-icon" style="width:${px}px;height:${px}px;font-size:${fontSize}px">${count}</div>`,
    className: "",
    iconSize: [px, px],
  });
}

function createMarkerIcon(color: string): L.DivIcon {
  return L.divIcon({
    html: `<div class="marker-dot" style="background:${color}"></div>`,
    className: "",
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function createEuIcon(): L.DivIcon {
  return L.divIcon({
    html: '<div class="eu-marker">EU</div>',
    className: "",
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

function buildPopupHtml(listing: Listing): string {
  const { photo_urls, street, district, price, area, land_area, rooms, floors, building_type, photo_count, url } = listing;

  const firstPhoto = photo_urls[0];
  const thumb = firstPhoto
    ? `<img class="popup-thumb" src="${escapeHtml(firstPhoto)}" alt="Listing photo" onerror="this.style.display='none'">`
    : "";

  const rows = [
    ["District", escapeHtml(district || "?")],
    ["Price", formatPrice(price) + (price != null ? "/mo" : "")],
    ["Building", area == null ? "?" : `${area} m²`],
    ["Land", land_area == null ? "?" : `${land_area} m²`],
    ["Rooms", formatNullable(rooms)],
    ["Floors", formatNullable(floors)],
    ["Type", escapeHtml(building_type || "?")],
    ["Photos", String(photo_count)],
  ].map(([label, value]) =>
    `<div class="detail-row"><span class="detail-label">${label}:</span> ${value}</div>`
  ).join("");

  const link = url
    ? `<div class="popup-link"><a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">View on BestHouse</a></div>`
    : "";

  return `<div class="popup-content">${thumb}<h3>${escapeHtml(street || "Unknown")}</h3>${rows}${link}</div>`;
}

export class MapController {
  private map: L.Map;
  private clusterGroup: L.MarkerClusterGroup;
  private markersById = new Map<number, L.Marker>();
  private euLatLng: L.LatLng;
  private openGallery: OpenGalleryFn;

  constructor({ eu, openGallery }: MapOptions) {
    this.euLatLng = L.latLng(eu.lat, eu.lng);
    this.openGallery = openGallery;

    this.map = L.map("map").setView([eu.lat, eu.lng], 14);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(this.map);

    this.clusterGroup = L.markerClusterGroup({
      maxClusterRadius: 1,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      iconCreateFunction: createClusterIcon,
    });
    this.map.addLayer(this.clusterGroup);

    L.marker([eu.lat, eu.lng], { icon: createEuIcon() })
      .addTo(this.map)
      .bindPopup("<b>EU Delegation</b><br>21 Frik St, Yerevan");
  }

  setView(lat: number, lng: number, zoom = 16): void {
    this.map.setView([lat, lng], zoom);
  }

  zoomToListing(id: number): void {
    const marker = this.markersById.get(id);
    if (!marker) return;
    this.clusterGroup.zoomToShowLayer(marker, () => marker.openPopup());
  }

  fitToListings(listings: Listing[]): void {
    if (listings.length === 0) return;
    const bounds = L.latLngBounds(listings.map((l) => [l.lat, l.lng] as [number, number]));
    bounds.extend(this.euLatLng);
    this.map.fitBounds(bounds, { padding: [30, 30] });
  }

  render(listings: Listing[]): void {
    this.clusterGroup.clearLayers();
    this.markersById.clear();

    for (const listing of listings) {
      const marker = L.marker([listing.lat, listing.lng], {
        icon: createMarkerIcon(priceColor(listing.price)),
      });

      marker.bindPopup(buildPopupHtml(listing), { maxWidth: 350 });

      marker.on("popupopen", (e) => {
        const thumb = e.popup.getElement()?.querySelector<HTMLImageElement>("img.popup-thumb");
        thumb?.addEventListener("click", () => this.openGallery(listing.photo_urls), { once: true });
      });

      this.clusterGroup.addLayer(marker);
      this.markersById.set(listing.id, marker);
    }
  }
}
