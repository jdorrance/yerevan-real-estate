type Primitive = string | number | null | undefined;

export function comparePrimitive(a: Primitive, b: Primitive, asc: boolean): number {
  const aNull = a == null;
  const bNull = b == null;

  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;

  let result: number;
  if (typeof a === "string" && typeof b === "string") {
    result = a.localeCompare(b);
  } else {
    result = Number(a) - Number(b);
  }

  return asc ? result : -result;
}
