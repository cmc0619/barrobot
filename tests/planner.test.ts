import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { DomainError } from "../src/domain/errors.js";
import type { InventoryItem, Recipe, Settings } from "../src/domain/model.js";
import { buildDrinkPlan, buildMenu } from "../src/domain/planner.js";

const settings: Settings = {
  cocktailDbApiKey: "1",
  motionSocket: "/tmp/motion.sock",
  maxDoseErrorPercent: 20,
  listenHost: "127.0.0.1",
  listenPort: 5000,
};

const inventory: InventoryItem[] = [
  {
    id: "gin",
    name: "London Dry Gin",
    aliases: ["gin"],
    mode: "bottle",
    enabled: true,
    slot: 2,
    mlPerPress: 15,
    pressDurationMs: 600,
    releaseDurationMs: 200,
  },
  {
    id: "lime",
    name: "lime",
    aliases: [],
    mode: "pantry",
    enabled: true,
    slot: null,
    mlPerPress: null,
    pressDurationMs: 600,
    releaseDurationMs: 200,
  },
];

const recipe: Recipe = {
  id: "test",
  source: "custom",
  name: "Test drink",
  imageUrl: null,
  instructions: "Mix",
  ingredients: [
    { name: "gin", amountMl: 45, originalMeasure: "45 ml", manual: false },
    { name: "lime", amountMl: null, originalMeasure: "1 wedge", manual: true },
  ],
};

describe("buildDrinkPlan", () => {
  it("resolves aliases, calibrated presses, and pantry steps", () => {
    const plan = buildDrinkPlan(recipe, inventory, settings);
    assert.equal(plan.steps[0]?.kind, "automatic");
    assert.deepEqual(plan.steps[0], {
      kind: "automatic",
      ingredientName: "gin",
      inventoryId: "gin",
      slot: 2,
      requestedMl: 45,
      deliveredMl: 45,
      pressCount: 3,
      pressDurationMs: 600,
      releaseDurationMs: 200,
    });
    assert.equal(plan.steps[1]?.kind, "manual");
  });

  it("rejects missing inventory before returning a plan", () => {
    assert.throws(() => buildDrinkPlan(recipe, [], settings), DomainError);
  });

  it("rejects calibration error beyond the configured tolerance", () => {
    const badlyCalibrated = structuredClone(inventory);
    const gin = badlyCalibrated[0];
    assert.ok(gin);
    gin.mlPerPress = 30;
    assert.throws(
      () => buildDrinkPlan(recipe, badlyCalibrated, settings),
      (error: unknown) => error instanceof DomainError && error.code === "DOSE_ERROR",
    );
  });

  it("retains the unavailable reason in the menu", () => {
    const menu = buildMenu([recipe], [], settings);
    assert.equal(menu[0]?.makeable, false);
    assert.match(menu[0]?.reason ?? "", /Missing gin/);
  });
});
