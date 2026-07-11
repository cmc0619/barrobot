import { DomainError } from "./errors.js";
import type { DrinkPlan, InventoryItem, MenuRecipe, PlanStep, Recipe, Settings } from "./model.js";
import { normalizeIngredient } from "./normalize.js";

/** Builds an immutable, calibrated drink plan before any hardware operation begins. */
export function buildDrinkPlan(
  recipe: Recipe,
  inventory: readonly InventoryItem[],
  settings: Settings,
): DrinkPlan {
  if (recipe.productProfile !== settings.productProfile) {
    throw new DomainError(
      "PRODUCT_PROFILE_MISMATCH",
      `${recipe.name} belongs to the ${recipe.productProfile} profile`,
    );
  }
  const available = buildInventoryIndex(inventory);
  const steps: PlanStep[] = recipe.ingredients.map((ingredient) => {
    const item = available.get(normalizeIngredient(ingredient.name));
    if (!item) {
      throw new DomainError("MISSING_INGREDIENT", `Missing ${ingredient.name}`);
    }
    if (ingredient.manual || ingredient.amountMl === null || item.mode === "pantry") {
      return {
        kind: "manual",
        ingredientName: ingredient.name,
        amountMl: ingredient.amountMl,
        instruction: manualInstruction(ingredient.name, ingredient.amountMl),
      };
    }
    if (item.slot === null || item.mlPerPress === null || item.mlPerPress <= 0) {
      throw new DomainError("INVALID_CALIBRATION", `${item.name} is not calibrated`);
    }
    const pressCount = Math.max(1, Math.round(ingredient.amountMl / item.mlPerPress));
    const deliveredMl = pressCount * item.mlPerPress;
    const errorPercent = (Math.abs(deliveredMl - ingredient.amountMl) / ingredient.amountMl) * 100;
    if (errorPercent > settings.maxDoseErrorPercent) {
      throw new DomainError(
        "DOSE_ERROR",
        `${item.name} would deliver ${deliveredMl.toFixed(1)} ml for a ${ingredient.amountMl.toFixed(1)} ml dose`,
      );
    }
    return {
      kind: "automatic",
      ingredientName: ingredient.name,
      inventoryId: item.id,
      slot: item.slot,
      requestedMl: ingredient.amountMl,
      deliveredMl,
      pressCount,
      pressDurationMs: item.pressDurationMs,
      releaseDurationMs: item.releaseDurationMs,
    };
  });
  return structuredClone({ recipeId: recipe.id, recipeName: recipe.name, steps });
}

/** Evaluates every recipe for menu display without discarding the reason it is unavailable. */
export function buildMenu(
  recipes: readonly Recipe[],
  inventory: readonly InventoryItem[],
  settings: Settings,
): MenuRecipe[] {
  return recipes
    .filter((recipe) => recipe.productProfile === settings.productProfile)
    .map((recipe) => {
      try {
        buildDrinkPlan(recipe, inventory, settings);
        return { recipe, makeable: true, reason: null };
      } catch (error) {
        return {
          recipe,
          makeable: false,
          reason: error instanceof Error ? error.message : "Recipe is unavailable",
        };
      }
    });
}

function buildInventoryIndex(inventory: readonly InventoryItem[]): Map<string, InventoryItem> {
  const index = new Map<string, InventoryItem>();
  for (const item of inventory) {
    if (!item.enabled) {
      continue;
    }
    for (const name of [item.name, ...item.aliases]) {
      const key = normalizeIngredient(name);
      const existing = index.get(key);
      if (existing && existing.id !== item.id) {
        throw new DomainError("AMBIGUOUS_ALIAS", `${name} matches multiple inventory items`);
      }
      index.set(key, item);
    }
  }
  return index;
}

function manualInstruction(name: string, amountMl: number | null): string {
  return amountMl === null ? `Add ${name} to taste` : `Add ${amountMl.toFixed(1)} ml ${name}`;
}
