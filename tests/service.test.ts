import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { BarRobotService } from "../src/application/barrobot-service.js";
import type { InventoryItem, Job, Recipe, StateDocument } from "../src/domain/model.js";
import { createDefaultState } from "../src/domain/seed.js";
import {
  FakeMotionController,
  FakeRecipeSource,
  MemoryStateRepository,
  waitFor,
} from "./helpers.js";

const bottle: InventoryItem = {
  id: "gin",
  name: "gin",
  aliases: [],
  mode: "bottle",
  enabled: true,
  slot: 3,
  mlPerPress: 15,
  pressDurationMs: 600,
  releaseDurationMs: 200,
};

const pantry: InventoryItem = {
  id: "lime",
  name: "lime",
  aliases: [],
  mode: "pantry",
  enabled: true,
  slot: null,
  mlPerPress: null,
  pressDurationMs: 600,
  releaseDurationMs: 200,
};

const recipe: Recipe = {
  id: "drink",
  source: "custom",
  productProfile: "cocktail",
  stepOrder: "strict",
  name: "Queued drink",
  imageUrl: null,
  instructions: "Mix",
  ingredients: [
    { name: "gin", amountMl: 45, originalMeasure: "45 ml", manual: false },
    { name: "lime", amountMl: null, originalMeasure: "1 wedge", manual: true },
  ],
};

function stateWithRecipe(): StateDocument {
  const state = createDefaultState();
  state.inventoryProfiles.cocktail = [bottle, pantry];
  state.recipes = [recipe];
  return state;
}

describe("BarRobotService", () => {
  it("executes automatic steps and pauses for manual acknowledgement", async () => {
    const repository = new MemoryStateRepository(stateWithRecipe());
    const motion = new FakeMotionController();
    const service = new BarRobotService(repository, motion, new FakeRecipeSource());
    await service.initialize();
    const submitted = await service.submitJob("drink");
    await waitFor(() => service.getJob(submitted.id).status === "waiting_manual");
    assert.deepEqual(motion.calls.slice(0, 4), [
      "status",
      "beginJob",
      "move:3",
      "dispense:3:600:200",
    ]);
    await service.continueJob(submitted.id);
    await waitFor(() => service.getJob(submitted.id).status === "completed");
    assert.equal(service.getJob(submitted.id).currentStep, 2);
    assert.ok(motion.calls.includes("endJob"));
  });

  it("fails nonterminal jobs after application restart", async () => {
    const state = stateWithRecipe();
    const job: Job = {
      id: "interrupted",
      status: "running",
      plan: { recipeId: "drink", recipeName: "Queued drink", stepOrder: "strict", steps: [] },
      currentStep: 0,
      createdAt: new Date(0).toISOString(),
      updatedAt: new Date(0).toISOString(),
      error: null,
    };
    state.jobs = [job];
    const service = new BarRobotService(
      new MemoryStateRepository(state),
      new FakeMotionController(),
      new FakeRecipeSource(),
    );
    await service.initialize();
    assert.equal(service.getJob("interrupted").status, "failed");
    assert.match(service.getJob("interrupted").error ?? "", /restarted/);
  });

  it("stops the motion daemon and cancels active work", async () => {
    const service = new BarRobotService(
      new MemoryStateRepository(stateWithRecipe()),
      new FakeMotionController(),
      new FakeRecipeSource(),
    );
    await service.initialize();
    const job = await service.submitJob("drink");
    await waitFor(() => service.getJob(job.id).status === "waiting_manual");
    await service.stopMachine();
    assert.equal(service.getJob(job.id).status, "cancelled");
  });

  it("requires a disarmed, empty machine before switching product profile", async () => {
    const motion = new FakeMotionController();
    const service = new BarRobotService(
      new MemoryStateRepository(stateWithRecipe()),
      motion,
      new FakeRecipeSource(),
    );
    await service.initialize();
    const settings = service.snapshot().settings;
    settings.productProfile = "slushie";
    await assert.rejects(service.replaceSettings(settings), /Disarm/);
    await service.disarm();
    await service.replaceSettings(settings);
    assert.equal(service.snapshot().settings.productProfile, "slushie");
  });

  it("keeps cocktail and slushie slot maps independent across a changeover", async () => {
    const motion = new FakeMotionController();
    const service = new BarRobotService(
      new MemoryStateRepository(stateWithRecipe()),
      motion,
      new FakeRecipeSource(),
    );
    await service.initialize();
    await service.disarm();
    const slushieSettings = service.snapshot().settings;
    slushieSettings.productProfile = "slushie";
    await service.replaceSettings(slushieSettings);
    assert.deepEqual(service.inventory(), []);
    const slushieItem = { ...bottle, id: "blue-raspberry", name: "blue raspberry syrup", slot: 8 };
    await service.replaceInventory([slushieItem]);
    const cocktailSettings = service.snapshot().settings;
    cocktailSettings.productProfile = "cocktail";
    await service.replaceSettings(cocktailSettings);
    assert.deepEqual(service.inventory(), [bottle, pantry]);
  });

  it("sends changed motion tuning to the daemon while disarmed", async () => {
    const motion = new FakeMotionController();
    const service = new BarRobotService(
      new MemoryStateRepository(stateWithRecipe()),
      motion,
      new FakeRecipeSource(),
    );
    await service.initialize();
    await service.disarm();
    const settings = service.snapshot().settings;
    settings.motion.rampSteps = 180;
    settings.motionProfile = "custom";
    await service.replaceSettings(settings);
    assert.ok(motion.calls.includes("configure:180"));
  });
});
