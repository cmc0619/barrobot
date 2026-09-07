const NON_LIQUID_TERMS = [
  "slice",
  "wedge",
  "dash",
  "pinch",
  "sprig",
  "piece",
  "cube",
  "twist",
  "top up",
  "to taste",
];

const UNIT_TO_ML: Record<string, number> = {
  ml: 1,
  milliliter: 1,
  milliliters: 1,
  cl: 10,
  oz: 29.5735,
  ounce: 29.5735,
  ounces: 29.5735,
  tsp: 4.92892,
  teaspoon: 4.92892,
  teaspoons: 4.92892,
  tbsp: 14.7868,
  tablespoon: 14.7868,
  tablespoons: 14.7868,
  cup: 236.588,
  cups: 236.588,
};

/** Converts a recipe measure into milliliters or returns null when it is ambiguous. */
export function parseMeasureMl(raw: string | null | undefined): number | null {
  if (!raw) {
    return null;
  }
  const text = raw.trim().toLocaleLowerCase("en-US");
  if (NON_LIQUID_TERMS.some((term) => text.includes(term))) {
    return null;
  }
  const mixed = text.match(/^(\d+)\s+(\d+)\s*\/\s*(\d+)/);
  const simple = text.match(/^(\d+\s*\/\s*\d+|\d+(?:\.\d+)?)/);
  const unit = text.match(
    /\b(ml|milliliters?|cl|oz|ounces?|tsp|teaspoons?|tbsp|tablespoons?|cups?)\b/,
  );
  if (!unit?.[1]) {
    return null;
  }
  let quantity: number;
  if (mixed?.[1] && mixed[2] && mixed[3]) {
    const denominator = Number(mixed[3]);
    if (denominator === 0) {
      return null;
    }
    quantity = Number(mixed[1]) + Number(mixed[2]) / denominator;
  } else if (simple?.[1]) {
    const numberText = simple[1].replaceAll(/\s/g, "");
    if (numberText.includes("/")) {
      const [numeratorText, denominatorText] = numberText.split("/");
      const denominator = Number(denominatorText);
      if (!numeratorText || denominator === 0) {
        return null;
      }
      quantity = Number(numeratorText) / denominator;
    } else {
      quantity = Number(numberText);
    }
  } else {
    return null;
  }
  const multiplier = UNIT_TO_ML[unit[1]];
  return multiplier === undefined ? null : Math.round(quantity * multiplier * 100) / 100;
}
