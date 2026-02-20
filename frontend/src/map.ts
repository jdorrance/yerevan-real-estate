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

function createCenterIcon(): L.DivIcon {
  return L.divIcon({
    html: '<div class="center-marker">×</div>',
    className: "",
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

function buildPopupHtml(listing: Listing): string {
  const {
    photo_urls,
    street,
    district,
    price,
    area,
    land_area,
    rooms,
    floors,
    building_type,
    photo_count,
    url,
    facilities,
    amenities,
    description,
  } = listing;

  const firstPhoto = photo_urls[0];
  const thumb = firstPhoto
    ? `<img class="popup-thumb" src="${escapeHtml(firstPhoto)}" alt="Listing photo" onerror="this.style.display='none'">`
    : "";

  const facilitiesStr = (facilities ?? []).filter(Boolean).join(", ");
  const amenitiesStr = (amenities ?? []).filter(Boolean).join(", ");
  const desc = (description ?? "").trim();
  const descShort = desc.length > 420 ? `${desc.slice(0, 420).trim()}…` : desc;

  const rows = [
    ["District", escapeHtml(district || "?")],
    ["Price", formatPrice(price) + (price != null ? "/mo" : "")],
    ["Building", area == null ? "?" : `${area} m²`],
    ["Land", land_area == null ? "?" : `${land_area} m²`],
    ["Rooms", formatNullable(rooms)],
    ["Floors", formatNullable(floors)],
    ["Type", escapeHtml(building_type || "?")],
    ["Facilities", facilitiesStr ? escapeHtml(facilitiesStr) : "?"],
    ["Amenities", amenitiesStr ? escapeHtml(amenitiesStr) : "?"],
    ["Photos", String(photo_count)],
  ].map(([label, value]) =>
    `<div class="detail-row"><span class="detail-label">${label}:</span> ${value}</div>`
  ).join("");

  const link = url
    ? `<div class="popup-link"><a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">View on BestHouse</a></div>`
    : "";

  const descHtml = descShort ? `<div class="popup-desc">${escapeHtml(descShort)}</div>` : "";

  return `<div class="popup-content">${thumb}<h3>${escapeHtml(
    street || "Unknown"
  )}</h3><div class="popup-body">${rows}${descHtml}${link}</div></div>`;
}

export class MapController {
  private map: L.Map;
  private clusterGroup: L.MarkerClusterGroup;
  private markersById = new Map<number, L.Marker>();
  private euLatLng: L.LatLng;
  private openGallery: OpenGalleryFn;
  private isochroneLayer: L.GeoJSON | null = null;

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

    L.marker([eu.lat, eu.lng], { icon: createCenterIcon() })
      .addTo(this.map)
      .bindPopup("<b>Center point</b>");
  }

  setWalkingIsochrones(geojson: GeoJSON.FeatureCollection): void {
    // Replace existing layer (if any)
    if (this.isochroneLayer) {
      this.map.removeLayer(this.isochroneLayer);
      this.isochroneLayer = null;
    }

    const features = [...geojson.features].sort((a, b) => {
      const av = Number((a.properties as any)?.value ?? 0);
      const bv = Number((b.properties as any)?.value ?? 0);
      return bv - av; // draw largest first (behind)
    });

    const sorted: GeoJSON.FeatureCollection = { type: "FeatureCollection", features };

    const style: L.PathOptions | ((feature?: GeoJSON.Feature) => L.PathOptions) = (feature) => {
      const seconds = Number((feature?.properties as any)?.value ?? 0);
      const minutes = Math.round(seconds / 60);
      const { color, fillColor } = isochroneStyle(minutes);
      return {
        color,
        weight: 2,
        opacity: 0.9,
        fillColor,
        fillOpacity: 0.24,
      };
    };

    this.isochroneLayer = L.geoJSON(sorted as any, {
      style,
      interactive: false,
    });

    // Add behind markers.
    this.isochroneLayer.addTo(this.map);
    (this.isochroneLayer as any).bringToBack?.();
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

      marker.bindPopup(buildPopupHtml(listing), {
        maxWidth: 350,
        keepInView: true,
        autoPanPadding: [16, 16],
      });

      marker.on("popupopen", (e) => {
        const thumb = e.popup.getElement()?.querySelector<HTMLImageElement>("img.popup-thumb");
        thumb?.addEventListener("click", () => this.openGallery(listing.photo_urls), { once: true });
      });

      this.clusterGroup.addLayer(marker);
      this.markersById.set(listing.id, marker);
    }
  }
}

function isochroneStyle(minutes: number): { color: string; fillColor: string } {
  // High-contrast palette for dark basemap. Minutes are expected to be 15/30.
  if (minutes <= 15) return { color: "#00E5FF", fillColor: "#00E5FF" }; // cyan
  return { color: "#FFD400", fillColor: "#FFD400" }; // yellow
}
