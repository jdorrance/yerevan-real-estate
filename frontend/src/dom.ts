const escapeDiv = document.createElement("div");

export function escapeHtml(text: string): string {
  escapeDiv.textContent = text;
  return escapeDiv.innerHTML;
}

export function $(selector: string, parent: ParentNode = document): HTMLElement {
  const el = parent.querySelector<HTMLElement>(selector);
  if (!el) throw new Error(`Element not found: ${selector}`);
  return el;
}

export function td(text: string): HTMLTableCellElement {
  const cell = document.createElement("td");
  cell.textContent = text;
  return cell;
}

export function tdHtml(html: string): HTMLTableCellElement {
  const cell = document.createElement("td");
  cell.innerHTML = html;
  return cell;
}

export function formatPrice(price: number | null): string {
  return price == null ? "?" : `$${price.toLocaleString()}`;
}

export function formatNullable(value: number | null): string {
  return value == null ? "?" : String(value);
}
