import type { Listing } from "./types";

type Ring = Array<[lng: number, lat: number]>;

function pointInRing(lng: number, lat: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function extractOuterRings(geometry: GeoJSON.Geometry): Ring[] {
  if (geometry.type === "Polygon") {
    const outer = geometry.coordinates[0];
    return outer ? [outer.map((p) => [p[0]!, p[1]!] as [number, number])] : [];
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates
      .map((poly) => poly[0])
      .filter((ring): ring is GeoJSON.Position[] => ring != null)
      .map((ring) => ring.map((p) => [p[0]!, p[1]!] as [number, number]));
  }
  return [];
}

/**
 * Pre-compute a listing-id → walk-minutes lookup by testing each listing
 * against the 15-min and 30-min isochrone polygons.
 */
export function buildWalkingMinutesIndex(
  listings: readonly Listing[],
  geojson: GeoJSON.FeatureCollection,
): ReadonlyMap<number, number> {
  const ringsByMinutes = new Map<number, Ring[]>();

  for (const feature of geojson.features) {
    if (!feature.geometry) continue;
    const seconds = Number(feature.properties?.["value"] ?? NaN);
    if (!Number.isFinite(seconds)) continue;
    const minutes = Math.round(seconds / 60);
    if (minutes !== 15 && minutes !== 30) continue;
    const rings = extractOuterRings(feature.geometry);
    if (rings.length) ringsByMinutes.set(minutes, rings);
  }

  const rings15 = ringsByMinutes.get(15) ?? [];
  const rings30 = ringsByMinutes.get(30) ?? [];
  const index = new Map<number, number>();

  for (const listing of listings) {
    if (rings15.some((r) => pointInRing(listing.lng, listing.lat, r))) {
      index.set(listing.id, 15);
    } else if (rings30.some((r) => pointInRing(listing.lng, listing.lat, r))) {
      index.set(listing.id, 30);
    }
  }

  return index;
}
