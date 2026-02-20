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
  private baseLayers: Record<string, L.TileLayer> = {};
  private overlayLayers: Record<string, L.Layer> = {};
  private clusterGroup: L.MarkerClusterGroup;
  private markersById = new Map<number, L.Marker>();
  private euLatLng: L.LatLng;
  private openGallery: OpenGalleryFn;
  private isochroneLayer: L.GeoJSON | null = null;
  private greensLayer: L.GeoJSON | null = null;

  constructor({ eu, openGallery }: MapOptions) {
    this.euLatLng = L.latLng(eu.lat, eu.lng);
    this.openGallery = openGallery;

    this.map = L.map("map").setView([eu.lat, eu.lng], 14);

    // Basemaps and overlays.
    const osmAttrib =
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    const cartoAttrib = `${osmAttrib} &copy; <a href="https://carto.com/attributions">CARTO</a>`;
    const esriAttrib = 'Tiles &copy; <a href="https://www.esri.com/">Esri</a>';
    const opentopoAttrib = `${osmAttrib} &copy; <a href="https://opentopomap.org">OpenTopoMap</a>`;

    const cartoLight = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd",
      maxZoom: 20,
      attribution: cartoAttrib,
    });
    const cartoVoyager = L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd",
      maxZoom: 20,
      attribution: cartoAttrib,
    });
    const osmStandard = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: osmAttrib,
    });
    const openTopo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
      maxZoom: 17,
      attribution: opentopoAttrib,
    });
    const esriWorldImagery = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: esriAttrib }
    );

    // Terrain shading overlay (works on top of any base).
    const esriHillshade = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: esriAttrib, opacity: 0.35 }
    );

    this.baseLayers = {
      English: cartoLight,
      Voyager: cartoVoyager,
      OSM: osmStandard,
      Topo: openTopo,
      Satellite: esriWorldImagery,
    };
    this.overlayLayers = {
      Hillshade: esriHillshade,
    };

    cartoVoyager.addTo(this.map);
    // Default overlays (user preference): hillshade on.
    esriHillshade.addTo(this.map);
    L.control.layers(this.baseLayers, this.overlayLayers, { position: "topleft" }).addTo(this.map);

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
        weight: 3,
        opacity: 1,
        fillColor,
        fillOpacity: 0.32,
        dashArray: minutes <= 15 ? undefined : "6 5",
      };
    };

    this.isochroneLayer = L.geoJSON(sorted as any, {
      style,
      interactive: false,
    });

    // Add above greens but below markers.
    this.isochroneLayer.addTo(this.map);
    (this.isochroneLayer as any).bringToFront?.();
  }

  setWalkingIsochronesVisible(visible: boolean): void {
    if (!this.isochroneLayer) return;
    if (visible) this.isochroneLayer.addTo(this.map);
    else this.map.removeLayer(this.isochroneLayer);
  }

  setGreens(geojson: GeoJSON.FeatureCollection): void {
    if (this.greensLayer) {
      this.map.removeLayer(this.greensLayer);
      this.greensLayer = null;
    }

    const style: L.PathOptions | ((feature?: GeoJSON.Feature) => L.PathOptions) = (feature) => {
      const kind = String((feature?.properties as any)?.kind ?? "");
      if (kind === "dog_park") {
        return { color: "#00E676", weight: 2, opacity: 0.95, fillColor: "#00E676", fillOpacity: 0.18 };
      }
      if (kind === "garden") {
        return { color: "#76FF03", weight: 2, opacity: 0.9, fillColor: "#76FF03", fillOpacity: 0.12 };
      }
      // park (default)
      return { color: "#1BFF8A", weight: 2, opacity: 0.85, fillColor: "#1BFF8A", fillOpacity: 0.10 };
    };

    this.greensLayer = L.geoJSON(geojson as any, {
      style,
      interactive: false,
      pointToLayer: (_f, latlng) => L.circleMarker(latlng, { radius: 4, color: "#1BFF8A", weight: 2, fillOpacity: 0.6 }),
    });

    this.greensLayer.addTo(this.map);
    (this.greensLayer as any).bringToBack?.();
  }

  setGreensVisible(visible: boolean): void {
    if (!this.greensLayer) return;
    if (visible) this.greensLayer.addTo(this.map);
    else this.map.removeLayer(this.greensLayer);
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
  return { color: "#FF2D95", fillColor: "#FF2D95" }; // magenta
}
