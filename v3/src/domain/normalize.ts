/** Normalizes an ingredient name for matching without changing its display value. */
export function normalizeIngredient(value: string): string {
  return value.trim().toLocaleLowerCase("en-US").replaceAll(/\s+/g, " ");
}
