import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";

import { PRICE_BRACKETS, priceColor } from "./config";
import { hasFavorite, removeFavorite, toggleFavorite } from "./favorites";
import { hasDislike, removeDislike, toggleDislike } from "./dislikes";
import { createLayerSets } from "./mapLayers";
import { buildPopupHtml } from "./mapPopup";
import type { LatLng, Listing } from "./types";

export type OpenGalleryFn = (photos: string[]) => void;
export type PreloadPhotosFn = (photos: string[]) => void;

export interface MapView {
  lat: number;
  lng: number;
  zoom: number;
}

interface MapOptions {
  center: LatLng;
  initialView?: MapView;
  openGallery: OpenGalleryFn;
  preloadPhotos?: PreloadPhotosFn;
}

// ---------------------------------------------------------------------------
// Icon factories
// ---------------------------------------------------------------------------

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

function createMarkerIconWithFavorite(color: string, favorite: boolean): L.DivIcon {
  return L.divIcon({
    html: `<div class="marker-dot" style="background:${color}">${favorite ? '<span class="marker-fav-badge">★</span>' : ""}</div>`,
    className: "",
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function createDislikedMarkerIcon(): L.DivIcon {
  return L.divIcon({
    html: '<div class="marker-x">×</div>',
    className: "",
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function createListingIcon(listing: Listing): L.DivIcon {
  if (hasDislike(listing.url)) return createDislikedMarkerIcon();
  return createMarkerIconWithFavorite(priceColor(listing.price), hasFavorite(listing.url));
}

function createCenterIcon(): L.DivIcon {
  return L.divIcon({
    html: '<div class="center-marker">×</div>',
    className: "",
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

// ---------------------------------------------------------------------------
// Isochrone styling
// ---------------------------------------------------------------------------

function isochroneStyle(minutes: number): { color: string; fillColor: string } {
  if (minutes <= 15) return { color: "#00E5FF", fillColor: "#00E5FF" };
  return { color: "#FF2D95", fillColor: "#FF2D95" };
}

// ---------------------------------------------------------------------------
// Price legend (rendered as a Leaflet control inside the map)
// ---------------------------------------------------------------------------

const LEGEND_LABELS: Record<string, string> = {
  low: "≤$2,500",
  mid1: "$2,501–$3,500",
  mid2: "$3,501–$4,200",
  high: "$4,201+",
};

function createLegendControl(): L.Control {
  const Legend = L.Control.extend({
    onAdd() {
      const container = L.DomUtil.create("div", "map-legend");
      for (const b of PRICE_BRACKETS) {
        const row = L.DomUtil.create("div", "map-legend-item", container);
        const dot = L.DomUtil.create("span", "map-legend-dot", row);
        dot.style.background = b.color;
        row.appendChild(document.createTextNode(` ${LEGEND_LABELS[b.label] ?? b.label}`));
      }
      const centerRow = L.DomUtil.create("div", "map-legend-item", container);
      const xDot = L.DomUtil.create("span", "map-legend-dot map-legend-center", centerRow);
      xDot.textContent = "×";
      centerRow.appendChild(document.createTextNode(" Center"));
      return container;
    },
  });
  return new Legend({ position: "bottomright" });
}

const GREEN_STYLES: Record<string, L.PathOptions> = {
  dog_park: { color: "#00E676", weight: 2, opacity: 0.95, fillColor: "#00E676", fillOpacity: 0.18 },
  garden:   { color: "#76FF03", weight: 2, opacity: 0.9,  fillColor: "#76FF03", fillOpacity: 0.12 },
  park:     { color: "#1BFF8A", weight: 2, opacity: 0.85, fillColor: "#1BFF8A", fillOpacity: 0.10 },
};

// ---------------------------------------------------------------------------
// MapController
// ---------------------------------------------------------------------------

export class MapController {
  private readonly map: L.Map;
  private readonly clusterGroup: L.MarkerClusterGroup;
  private readonly markersById = new Map<number, L.Marker>();
  private readonly centerLatLng: L.LatLng;
  private readonly openGallery: OpenGalleryFn;
  private readonly preloadPhotos?: PreloadPhotosFn;

  private isochroneLayer: L.GeoJSON | null = null;
  private greensLayer: L.GeoJSON | null = null;

  constructor({ center, initialView, openGallery, preloadPhotos }: MapOptions) {
    this.centerLatLng = L.latLng(center.lat, center.lng);
    this.openGallery = openGallery;
    this.preloadPhotos = preloadPhotos;

    const startLat = initialView?.lat ?? center.lat;
    const startLng = initialView?.lng ?? center.lng;
    const startZoom = initialView?.zoom ?? 16;
    this.map = L.map("map").setView([startLat, startLng], startZoom);

    const layers = createLayerSets();
    layers.defaultBase.addTo(this.map);
    for (const overlay of layers.defaultOverlays) overlay.addTo(this.map);
    L.control.layers(layers.baseLayers, layers.overlayLayers, { position: "topleft" }).addTo(this.map);
    createLegendControl().addTo(this.map);

    this.clusterGroup = L.markerClusterGroup({
      maxClusterRadius: 1,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      iconCreateFunction: createClusterIcon,
    });
    this.map.addLayer(this.clusterGroup);

    L.marker([center.lat, center.lng], { icon: createCenterIcon() })
      .addTo(this.map)
      .bindPopup("<b>Center point</b>");
  }

  // --- Isochrones ----------------------------------------------------------

  setWalkingIsochrones(geojson: GeoJSON.FeatureCollection): void {
    if (this.isochroneLayer) {
      this.map.removeLayer(this.isochroneLayer);
      this.isochroneLayer = null;
    }

    const features = [...geojson.features].sort((a, b) => {
      const av = Number(a.properties?.["value"] ?? 0);
      const bv = Number(b.properties?.["value"] ?? 0);
      return bv - av;
    });

    const sorted: GeoJSON.FeatureCollection = { type: "FeatureCollection", features };
    this.isochroneLayer = L.geoJSON(sorted, {
      style: (feature) => {
        const seconds = Number(feature?.properties?.["value"] ?? 0);
        const minutes = Math.round(seconds / 60);
        const { color, fillColor } = isochroneStyle(minutes);
        return {
          color, fillColor,
          weight: 3,
          opacity: 1,
          fillOpacity: 0.32,
          dashArray: minutes <= 15 ? undefined : "6 5",
        };
      },
      interactive: false,
    });

    this.isochroneLayer.addTo(this.map);
    this.isochroneLayer.bringToFront();
  }

  setWalkingIsochronesVisible(visible: boolean): void {
    if (!this.isochroneLayer) return;
    if (visible) this.isochroneLayer.addTo(this.map);
    else this.map.removeLayer(this.isochroneLayer);
  }

  // --- Green spaces --------------------------------------------------------

  setGreens(geojson: GeoJSON.FeatureCollection): void {
    if (this.greensLayer) {
      this.map.removeLayer(this.greensLayer);
      this.greensLayer = null;
    }

    this.greensLayer = L.geoJSON(geojson, {
      style: (feature) => {
        const kind = String(feature?.properties?.["kind"] ?? "park");
        return GREEN_STYLES[kind] ?? GREEN_STYLES["park"]!;
      },
      interactive: false,
      pointToLayer: (_f, latlng) =>
        L.circleMarker(latlng, { radius: 4, color: "#1BFF8A", weight: 2, fillOpacity: 0.6 }),
    });

    this.greensLayer.addTo(this.map);
    this.greensLayer.bringToBack();
  }

  setGreensVisible(visible: boolean): void {
    if (!this.greensLayer) return;
    if (visible) this.greensLayer.addTo(this.map);
    else this.map.removeLayer(this.greensLayer);
  }

  // --- View helpers --------------------------------------------------------

  getView(): MapView {
    const c = this.map.getCenter();
    return { lat: c.lat, lng: c.lng, zoom: this.map.getZoom() };
  }

  onMoveEnd(cb: () => void): void {
    this.map.on("moveend", cb);
  }

  setView(lat: number, lng: number, zoom = 16): void {
    this.map.setView([lat, lng], zoom);
  }

  invalidateSize(): void {
    this.map.invalidateSize();
  }

  zoomToListing(id: number): void {
    const marker = this.markersById.get(id);
    if (!marker) return;
    this.clusterGroup.zoomToShowLayer(marker, () => marker.openPopup());
  }

  fitToListings(listings: readonly Listing[]): void {
    if (listings.length === 0) return;
    const bounds = L.latLngBounds(listings.map((l) => [l.lat, l.lng] as [number, number]));
    bounds.extend(this.centerLatLng);
    this.map.fitBounds(bounds, { padding: [30, 30] });
  }

  // --- Marker rendering ----------------------------------------------------

  render(listings: readonly Listing[]): void {
    this.clusterGroup.clearLayers();
    this.markersById.clear();

    for (const listing of listings) {
      const marker = L.marker([listing.lat, listing.lng], {
        icon: createListingIcon(listing),
      });

      marker.bindPopup(buildPopupHtml(listing, hasFavorite(listing.url)), {
        maxWidth: 350,
        keepInView: true,
        autoPanPadding: [16, 16],
      });

      marker.on("popupopen", (e) => {
        this.preloadPhotos?.(listing.photo_urls);
        const thumb = e.popup.getElement()?.querySelector<HTMLImageElement>("img.popup-thumb");
        thumb?.addEventListener("click", () => this.openGallery(listing.photo_urls), { once: true });

        const favBtn = e.popup.getElement()?.querySelector<HTMLButtonElement>("button[data-action='favorite']");
        if (favBtn) {
          // Ensure the UI reflects latest state even if favorites changed after initial render.
          const isFavNow = hasFavorite(listing.url);
          favBtn.classList.toggle("active", isFavNow);
          favBtn.textContent = isFavNow ? "★" : "☆";

          favBtn.addEventListener("click", (evt) => {
            evt.preventDefault();
            evt.stopPropagation();
            // Mutual exclusivity: favoriting clears dislike.
            removeDislike(listing.url);
            const next = toggleFavorite(listing.url);
            favBtn.classList.toggle("active", next);
            favBtn.textContent = next ? "★" : "☆";
            marker.setIcon(createListingIcon(listing));
          });
        }

        const dislikeBtn = e.popup.getElement()?.querySelector<HTMLButtonElement>("button[data-action='dislike']");
        if (dislikeBtn) {
          const isDislikedNow = hasDislike(listing.url);
          dislikeBtn.classList.toggle("active", isDislikedNow);
          dislikeBtn.textContent = "×";

          dislikeBtn.addEventListener("click", (evt) => {
            evt.preventDefault();
            evt.stopPropagation();
            // Mutual exclusivity: disliking clears favorite.
            removeFavorite(listing.url);
            const next = toggleDislike(listing.url);
            dislikeBtn.classList.toggle("active", next);
            marker.setIcon(createListingIcon(listing));
          });
        }
      });

      this.clusterGroup.addLayer(marker);
      this.markersById.set(listing.id, marker);
    }
  }
}
