import { escapeHtml, formatNullable, formatPrice } from "./dom";
import type { Listing } from "./types";

const DESC_MAX_LENGTH = 420;

export function buildPopupHtml(listing: Listing): string {
  const firstPhoto = listing.photo_urls[0];
  const thumb = firstPhoto
    ? `<img class="popup-thumb" src="${escapeHtml(firstPhoto)}" alt="Listing photo" onerror="this.style.display='none'">`
    : "";

  const facilitiesStr = listing.facilities.filter(Boolean).join(", ");
  const amenitiesStr = listing.amenities.filter(Boolean).join(", ");
  const desc = listing.description.trim();
  const descShort = desc.length > DESC_MAX_LENGTH ? `${desc.slice(0, DESC_MAX_LENGTH).trim()}…` : desc;

  const rows: [string, string][] = [
    ["District", escapeHtml(listing.district || "?")],
    ["Price", formatPrice(listing.price) + (listing.price != null ? "/mo" : "")],
    ["Building", listing.area == null ? "?" : `${listing.area} m²`],
    ["Land", listing.land_area == null ? "?" : `${listing.land_area} m²`],
    ["Rooms", formatNullable(listing.rooms)],
    ["Floors", formatNullable(listing.floors)],
    ["Type", escapeHtml(listing.building_type || "?")],
    ["Facilities", facilitiesStr ? escapeHtml(facilitiesStr) : "?"],
    ["Amenities", amenitiesStr ? escapeHtml(amenitiesStr) : "?"],
    ["Photos", String(listing.photo_count)],
  ];

  const rowsHtml = rows
    .map(([label, value]) => `<div class="detail-row"><span class="detail-label">${label}:</span> ${value}</div>`)
    .join("");

  const link = listing.url
    ? `<div class="popup-link"><a href="${escapeHtml(listing.url)}" target="_blank" rel="noreferrer">View on BestHouse</a></div>`
    : "";

  const descHtml = descShort
    ? `<div class="popup-desc">${escapeHtml(descShort)}</div>`
    : "";

  return [
    '<div class="popup-content">',
    thumb,
    `<h3>${escapeHtml(listing.street || "Unknown")}</h3>`,
    `<div class="popup-body">${rowsHtml}${descHtml}${link}</div>`,
    "</div>",
  ].join("");
}
