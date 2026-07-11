export const SLOT_COUNT = 12;

export type InventoryMode = "bottle" | "pantry";

export interface InventoryItem {
  id: string;
  name: string;
  aliases: string[];
  mode: InventoryMode;
  enabled: boolean;
  slot: number | null;
  mlPerPress: number | null;
  pressDurationMs: number;
  releaseDurationMs: number;
}

export interface RecipeIngredient {
  name: string;
  amountMl: number | null;
  originalMeasure: string;
  manual: boolean;
}

export interface Recipe {
  id: string;
  source: "seed" | "cocktaildb" | "custom";
  name: string;
  imageUrl: string | null;
  instructions: string;
  ingredients: RecipeIngredient[];
}

export interface Settings {
  cocktailDbApiKey: string;
  motionSocket: string;
  maxDoseErrorPercent: number;
  listenHost: string;
  listenPort: number;
}

export interface AutomaticPlanStep {
  kind: "automatic";
  ingredientName: string;
  inventoryId: string;
  slot: number;
  requestedMl: number;
  deliveredMl: number;
  pressCount: number;
  pressDurationMs: number;
  releaseDurationMs: number;
}

export interface ManualPlanStep {
  kind: "manual";
  ingredientName: string;
  amountMl: number | null;
  instruction: string;
}

export type PlanStep = AutomaticPlanStep | ManualPlanStep;

export interface DrinkPlan {
  recipeId: string;
  recipeName: string;
  steps: PlanStep[];
}

export type JobStatus =
  "queued" | "running" | "waiting_manual" | "completed" | "failed" | "cancelled";

export interface Job {
  id: string;
  status: JobStatus;
  plan: DrinkPlan;
  currentStep: number;
  createdAt: string;
  updatedAt: string;
  error: string | null;
}

export interface StateDocument {
  schemaVersion: 1;
  settings: Settings;
  inventory: InventoryItem[];
  recipes: Recipe[];
  jobs: Job[];
}

export interface MenuRecipe {
  recipe: Recipe;
  makeable: boolean;
  reason: string | null;
}
