import { DomainError } from "../domain/errors.js";
import {
  type Job,
  type Recipe,
  SLOT_COUNT,
  type InventoryItem,
  type Settings,
  type StateDocument,
} from "../domain/model.js";

/** Validates the persisted v3 state document before it enters the application. */
export function validateStateDocument(value: unknown): asserts value is StateDocument {
  if (!isRecord(value) || value.schemaVersion !== 1) {
    throw new DomainError("INVALID_STATE", "State file is not BarRobot schema version 1");
  }
  validateSettings(value.settings);
  if (
    !Array.isArray(value.inventory) ||
    !Array.isArray(value.recipes) ||
    !Array.isArray(value.jobs)
  ) {
    throw new DomainError("INVALID_STATE", "State collections must be arrays");
  }
  validateInventory(value.inventory);
  validateRecipes(value.recipes);
  validateJobs(value.jobs);
}

function validateRecipes(value: unknown[]): asserts value is Recipe[] {
  for (const recipe of value) {
    if (
      !isRecord(recipe) ||
      typeof recipe.id !== "string" ||
      typeof recipe.name !== "string" ||
      (recipe.source !== "seed" && recipe.source !== "cocktaildb" && recipe.source !== "custom") ||
      (recipe.imageUrl !== null && typeof recipe.imageUrl !== "string") ||
      typeof recipe.instructions !== "string" ||
      !Array.isArray(recipe.ingredients)
    ) {
      throw new DomainError("INVALID_STATE", "Recipe entry contains invalid values");
    }
    for (const ingredient of recipe.ingredients) {
      if (
        !isRecord(ingredient) ||
        typeof ingredient.name !== "string" ||
        (ingredient.amountMl !== null &&
          (typeof ingredient.amountMl !== "number" || ingredient.amountMl <= 0)) ||
        typeof ingredient.originalMeasure !== "string" ||
        typeof ingredient.manual !== "boolean"
      ) {
        throw new DomainError("INVALID_STATE", `Recipe ${recipe.id} has an invalid ingredient`);
      }
    }
  }
}

function validateJobs(value: unknown[]): asserts value is Job[] {
  const statuses = new Set([
    "queued",
    "running",
    "waiting_manual",
    "completed",
    "failed",
    "cancelled",
  ]);
  for (const job of value) {
    if (
      !isRecord(job) ||
      typeof job.id !== "string" ||
      typeof job.status !== "string" ||
      !statuses.has(job.status) ||
      !isRecord(job.plan) ||
      typeof job.plan.recipeId !== "string" ||
      typeof job.plan.recipeName !== "string" ||
      !Array.isArray(job.plan.steps) ||
      typeof job.currentStep !== "number" ||
      !Number.isInteger(job.currentStep) ||
      job.currentStep < 0 ||
      typeof job.createdAt !== "string" ||
      typeof job.updatedAt !== "string" ||
      (job.error !== null && typeof job.error !== "string")
    ) {
      throw new DomainError("INVALID_STATE", "Job entry contains invalid values");
    }
  }
}

/** Validates settings accepted from persistence or the HTTP API. */
export function validateSettings(value: unknown): asserts value is Settings {
  if (!isRecord(value)) {
    throw new DomainError("INVALID_SETTINGS", "Settings must be an object");
  }
  if (
    typeof value.cocktailDbApiKey !== "string" ||
    typeof value.motionSocket !== "string" ||
    typeof value.listenHost !== "string" ||
    typeof value.listenPort !== "number" ||
    !Number.isInteger(value.listenPort) ||
    value.listenPort < 1 ||
    value.listenPort > 65535 ||
    typeof value.maxDoseErrorPercent !== "number" ||
    value.maxDoseErrorPercent < 0 ||
    value.maxDoseErrorPercent > 100
  ) {
    throw new DomainError("INVALID_SETTINGS", "Settings contain invalid values");
  }
}

/** Validates inventory calibration, identifiers, aliases, and unique bottle slots. */
export function validateInventory(value: unknown): asserts value is InventoryItem[] {
  if (!Array.isArray(value)) {
    throw new DomainError("INVALID_INVENTORY", "Inventory must be an array");
  }
  const ids = new Set<string>();
  const slots = new Set<number>();
  for (const item of value) {
    if (!isRecord(item)) {
      throw new DomainError("INVALID_INVENTORY", "Inventory entries must be objects");
    }
    if (
      typeof item.id !== "string" ||
      item.id.length === 0 ||
      typeof item.name !== "string" ||
      item.name.trim().length === 0 ||
      !Array.isArray(item.aliases) ||
      !item.aliases.every((alias) => typeof alias === "string") ||
      (item.mode !== "bottle" && item.mode !== "pantry") ||
      typeof item.enabled !== "boolean" ||
      typeof item.pressDurationMs !== "number" ||
      item.pressDurationMs < 1 ||
      typeof item.releaseDurationMs !== "number" ||
      item.releaseDurationMs < 0
    ) {
      throw new DomainError("INVALID_INVENTORY", "Inventory entry contains invalid values");
    }
    if (ids.has(item.id)) {
      throw new DomainError("INVALID_INVENTORY", `Duplicate inventory id ${item.id}`);
    }
    ids.add(item.id);
    if (item.mode === "bottle") {
      if (
        typeof item.slot !== "number" ||
        !Number.isInteger(item.slot) ||
        item.slot < 0 ||
        item.slot >= SLOT_COUNT ||
        typeof item.mlPerPress !== "number" ||
        item.mlPerPress <= 0
      ) {
        throw new DomainError("INVALID_INVENTORY", `${item.name} requires a slot and calibration`);
      }
      if (slots.has(item.slot)) {
        throw new DomainError("INVALID_INVENTORY", `Bottle slot ${item.slot + 1} is duplicated`);
      }
      slots.add(item.slot);
    } else if (item.slot !== null || item.mlPerPress !== null) {
      throw new DomainError("INVALID_INVENTORY", `${item.name} pantry configuration is invalid`);
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
