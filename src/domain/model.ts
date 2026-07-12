export const SLOT_COUNT = 12;

export type InventoryMode = "bottle" | "pantry";
export type ProductProfile = "cocktail" | "slushie";
export type MotionProfileId = "gentle" | "balanced" | "quick" | "custom";
export type CompletionSound = "off" | "chime" | "fanfare";
export type MachinePersonality = "classic" | "tropical" | "arcade";
export type StepOrder = "strict" | "flexible";

export interface MotionSettings {
  minimumHalfPeriodUs: number;
  maximumHalfPeriodUs: number;
  rampSteps: number;
  settleMs: number;
  holdPosition: boolean;
}

export interface InventoryItem {
  id: string;
  name: string;
  aliases: string[];
  mode: InventoryMode;
  enabled: boolean;
  slot: number | null;
  mlPerPress: number | null;
  estimatedFillPercent: number | null;
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
  productProfile: ProductProfile;
  stepOrder: StepOrder;
  name: string;
  imageUrl: string | null;
  instructions: string;
  ingredients: RecipeIngredient[];
}

export interface Settings {
  productProfile: ProductProfile;
  cocktailDbApiKey: string;
  motionSocket: string;
  maxDoseErrorPercent: number;
  listenHost: string;
  listenPort: number;
  motionProfile: MotionProfileId;
  motion: MotionSettings;
  completionSound: CompletionSound;
  personality: MachinePersonality;
  partyMode: boolean;
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
  stepOrder: StepOrder;
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
  schemaVersion: 4;
  settings: Settings;
  inventoryProfiles: Record<ProductProfile, InventoryItem[]>;
  recipes: Recipe[];
  jobs: Job[];
}

export interface MenuRecipe {
  recipe: Recipe;
  makeable: boolean;
  reason: string | null;
}
