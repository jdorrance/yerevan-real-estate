import { escapeHtml, formatNullable, formatPrice } from "./dom";
import type { Listing } from "./types";

const DESC_MAX_LENGTH = 420;

export function buildPopupHtml(listing: Listing, isFavorite: boolean): string {
  const firstPhoto = listing.photo_urls[0];
  const thumb = firstPhoto
    ? `<img class="popup-thumb" src="${escapeHtml(firstPhoto)}" alt="Listing photo" onerror="this.style.display='none'">`
    : "";

  const facilitiesStr = listing.facilities.filter(Boolean).join(", ");
  const amenitiesStr = listing.amenities.filter(Boolean).join(", ");
  const desc = listing.description.trim();
  const descShort = desc.length > DESC_MAX_LENGTH ? `${desc.slice(0, DESC_MAX_LENGTH).trim()}…` : desc;

  const addrRow: string = listing.resolved_address
    ? `<div class="popup-resolved-addr"><span class="detail-label">Address:</span> ${escapeHtml(listing.resolved_address)}${
        listing.resolved_address_confidence
          ? ` <span class="popup-addr-conf popup-addr-conf--${listing.resolved_address_confidence.toLowerCase()}">${listing.resolved_address_confidence}</span>`
          : ""
      }</div>`
    : "";

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

  const sourceLabel = listing.source === "kentron" ? "Kentron" : "BestHouse";
  const link2 = listing.url
    ? `<div class="popup-link"><a href="${escapeHtml(listing.url)}" target="_blank" rel="noreferrer">View on ${sourceLabel}</a></div>`
    : "";

  const descHtml = descShort
    ? `<div class="popup-desc">${escapeHtml(descShort)}</div>`
    : "";

  const hasAi = listing.ai_summary.trim() || listing.ai_score != null;
  const score = listing.ai_score;
  const scoreClass =
    score == null
      ? ""
      : score >= 7
        ? "popup-ai-score--high"
        : score >= 5
          ? "popup-ai-score--mid"
          : "popup-ai-score--low";
  const aiBlock = hasAi
    ? [
        '<div class="popup-ai-review">',
        score != null
          ? `<span class="popup-ai-score ${scoreClass}" aria-label="Suitability score">${score}</span>`
          : "",
        listing.ai_summary.trim()
          ? `<div class="popup-ai-text">${escapeHtml(listing.ai_summary.trim())}</div>`
          : "",
        "</div>",
      ].join("")
    : "";

  const favIcon = isFavorite ? "★" : "☆";
  const favClass = isFavorite ? "popup-fav active" : "popup-fav";
  const favBtn = listing.url
    ? `<button class="${favClass}" type="button" data-action="favorite" data-url="${escapeHtml(
        listing.url
      )}" aria-label="Toggle favorite">${favIcon}</button>`
    : "";

  // Dislike state is determined at popup-open time (MapController) to avoid coupling this module.
  // We still render the button shell so MapController can toggle it.
  const dislikeBtn = listing.url
    ? `<button class="popup-dislike" type="button" data-action="dislike" data-url="${escapeHtml(
        listing.url
      )}" aria-label="Toggle dislike">×</button>`
    : "";

  return [
    '<div class="popup-content">',
    thumb,
    `<div class="popup-titlebar"><h3>${escapeHtml(listing.street || "Unknown")}</h3><div class="popup-actions">${favBtn}${dislikeBtn}</div></div>`,
    `<div class="popup-body">${addrRow}${aiBlock}${rowsHtml}${descHtml}${link2}</div>`,
    "</div>",
  ].join("");
}
