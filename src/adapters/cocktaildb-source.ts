import type { Recipe, RecipeIngredient } from "../domain/model.js";
import type { RecipeSource } from "../application/ports.js";
import { parseMeasureMl } from "../domain/measure.js";

interface CocktailDbDrink {
  idDrink?: string;
  strDrink?: string;
  strDrinkThumb?: string;
  strInstructions?: string;
  [key: string]: unknown;
}

interface CocktailDbResponse {
  drinks?: CocktailDbDrink[] | null;
}

/** Fetches and converts CocktailDB data only when an operator requests synchronization. */
export class CocktailDbSource implements RecipeSource {
  public async fetchAll(apiKey: string): Promise<Recipe[]> {
    const drinks = apiKey !== "1" ? await this.fetchPaid(apiKey) : await this.fetchFree();
    const recipes = new Map<string, Recipe>();
    for (const drink of drinks) {
      const recipe = convertDrink(drink);
      recipes.set(recipe.id, recipe);
    }
    return [...recipes.values()].sort((left, right) => left.name.localeCompare(right.name));
  }

  private async fetchPaid(apiKey: string): Promise<CocktailDbDrink[]> {
    const response = await fetchJson(
      `https://www.thecocktaildb.com/api/json/v2/${encodeURIComponent(apiKey)}/search.php?s=`,
    );
    return response.drinks ?? [];
  }

  private async fetchFree(): Promise<CocktailDbDrink[]> {
    const batches = await Promise.all(
      Array.from("abcdefghijklmnopqrstuvwxyz").map(async (letter) =>
        fetchJson(`https://www.thecocktaildb.com/api/json/v1/1/search.php?f=${letter}`),
      ),
    );
    return batches.flatMap((batch) => batch.drinks ?? []);
  }
}

async function fetchJson(url: string): Promise<CocktailDbResponse> {
  const response = await fetch(url, { signal: AbortSignal.timeout(15_000) });
  if (!response.ok) {
    throw new Error(`CocktailDB returned HTTP ${response.status}`);
  }
  return (await response.json()) as CocktailDbResponse;
}

function convertDrink(drink: CocktailDbDrink): Recipe {
  if (!drink.idDrink || !drink.strDrink) {
    throw new Error("CocktailDB recipe is missing an id or name");
  }
  const ingredients: RecipeIngredient[] = [];
  for (let index = 1; index <= 15; index += 1) {
    const name = stringValue(drink[`strIngredient${index}`]);
    if (!name) {
      continue;
    }
    const measure = stringValue(drink[`strMeasure${index}`]) ?? "";
    const amountMl = parseMeasureMl(measure);
    ingredients.push({
      name: name.trim(),
      amountMl,
      originalMeasure: measure.trim(),
      manual: amountMl === null,
    });
  }
  return {
    id: `cocktaildb:${drink.idDrink}`,
    source: "cocktaildb",
    name: drink.strDrink.trim(),
    imageUrl: drink.strDrinkThumb?.trim() || null,
    instructions: drink.strInstructions?.trim() || "",
    ingredients,
  };
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}
