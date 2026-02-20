import L from "leaflet";

export interface LayerSets {
  baseLayers: Record<string, L.TileLayer>;
  overlayLayers: Record<string, L.TileLayer>;
  defaultBase: L.TileLayer;
  defaultOverlays: L.TileLayer[];
}

const OSM_ATTRIB =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const CARTO_ATTRIB = `${OSM_ATTRIB} &copy; <a href="https://carto.com/attributions">CARTO</a>`;
const ESRI_ATTRIB = 'Tiles &copy; <a href="https://www.esri.com/">Esri</a>';
const TOPO_ATTRIB = `${OSM_ATTRIB} &copy; <a href="https://opentopomap.org">OpenTopoMap</a>`;

export function createLayerSets(): LayerSets {
  const cartoLight = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    { subdomains: "abcd", maxZoom: 20, attribution: CARTO_ATTRIB },
  );

  const cartoVoyager = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    { subdomains: "abcd", maxZoom: 20, attribution: CARTO_ATTRIB },
  );

  const osmStandard = L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: OSM_ATTRIB },
  );

  const openTopo = L.tileLayer(
    "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    { maxZoom: 17, attribution: TOPO_ATTRIB },
  );

  const esriImagery = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: ESRI_ATTRIB },
  );

  const esriHillshade = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: ESRI_ATTRIB, opacity: 0.35 },
  );

  return {
    baseLayers: {
      English: cartoLight,
      Voyager: cartoVoyager,
      OSM: osmStandard,
      Topo: openTopo,
      Satellite: esriImagery,
    },
    overlayLayers: {
      Hillshade: esriHillshade,
    },
    defaultBase: cartoVoyager,
    defaultOverlays: [esriHillshade],
  };
}
