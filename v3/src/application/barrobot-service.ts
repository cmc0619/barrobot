import { randomUUID } from "node:crypto";
import { DomainError } from "../domain/errors.js";
import type {
  InventoryItem,
  Job,
  MenuRecipe,
  Recipe,
  Settings,
  StateDocument,
} from "../domain/model.js";
import { buildDrinkPlan, buildMenu, optimizeFlexiblePlan } from "../domain/planner.js";
import { validateInventory, validateSettings } from "../adapters/state-validation.js";
import type { MotionController, MotionStatus, RecipeSource, StateRepository } from "./ports.js";

interface ManualWaiter {
  resolve: (proceed: boolean) => void;
}

/** Coordinates state, planning, machine commands, and the single FIFO drink queue. */
export class BarRobotService {
  private state: StateDocument | null = null;
  private pumping = false;
  private activeJobId: string | null = null;
  private readonly manualWaiters = new Map<string, ManualWaiter>();

  public constructor(
    private readonly repository: StateRepository,
    private readonly motion: MotionController,
    private readonly recipeSource: RecipeSource,
    private readonly now: () => Date = () => new Date(),
  ) {}

  /** Loads persisted state and fails jobs that could have partially executed before restart. */
  public async initialize(): Promise<void> {
    this.state = await this.repository.load();
    let changed = false;
    for (const job of this.state.jobs) {
      if (job.status === "queued" || job.status === "running" || job.status === "waiting_manual") {
        job.status = "failed";
        job.error = "Application restarted before the job completed";
        job.updatedAt = this.timestamp();
        changed = true;
      }
    }
    if (changed) {
      await this.persist();
    }
  }

  /** Returns an isolated state snapshot for HTTP and tests. */
  public snapshot(): StateDocument {
    return structuredClone(this.requireState());
  }

  /** Returns menu recipes with exact planning availability reasons. */
  public menu(): MenuRecipe[] {
    const state = this.requireState();
    return buildMenu(state.recipes, this.activeInventory(), state.settings);
  }

  /** Returns the inventory map belonging to the selected physical machine setup. */
  public inventory(): InventoryItem[] {
    return structuredClone(this.activeInventory());
  }

  /** Replaces validated inventory as one atomic state update. */
  public async replaceInventory(inventory: InventoryItem[]): Promise<InventoryItem[]> {
    validateInventory(inventory);
    const state = this.requireState();
    state.inventoryProfiles[state.settings.productProfile] = structuredClone(inventory);
    await this.persist();
    return this.inventory();
  }

  /** Replaces validated application settings. */
  public async replaceSettings(settings: Settings): Promise<Settings> {
    validateSettings(settings);
    const state = this.requireState();
    if (settings.productProfile !== state.settings.productProfile) {
      if (this.activeJobId || state.jobs.some((job) => job.status === "queued")) {
        throw new DomainError(
          "PROFILE_BUSY",
          "Finish or cancel queued work before changing product profile",
        );
      }
      const status = await this.motion.status();
      if (status.armed || status.state === "busy") {
        throw new DomainError(
          "PROFILE_ARMED",
          "Disarm the machine before changing product profile",
        );
      }
    }
    const motionChanged = JSON.stringify(settings.motion) !== JSON.stringify(state.settings.motion);
    if (motionChanged) {
      const status = await this.motion.status();
      if (status.armed || status.state === "busy") {
        throw new DomainError("MOTION_ARMED", "Disarm the machine before changing motion settings");
      }
      await this.motion.configure(settings.motion);
    }
    state.settings = structuredClone(settings);
    await this.persist();
    return structuredClone(state.settings);
  }

  /** Explicitly synchronizes the remote catalogue while retaining custom and seed recipes. */
  public async synchronizeRecipes(): Promise<Recipe[]> {
    const state = this.requireState();
    if (state.settings.productProfile !== "cocktail") {
      throw new DomainError(
        "PROFILE_UNAVAILABLE",
        "CocktailDB is only available in the cocktail profile",
      );
    }
    const downloaded = await this.recipeSource.fetchAll(state.settings.cocktailDbApiKey);
    state.recipes = [
      ...state.recipes.filter((recipe) => recipe.source !== "cocktaildb"),
      ...downloaded,
    ].sort((left, right) => left.name.localeCompare(right.name));
    await this.persist();
    return structuredClone(state.recipes);
  }

  /** Returns motion health without masking an offline daemon as a valid machine state. */
  public status(): Promise<MotionStatus> {
    return this.motion.status();
  }

  /** Applies stored tuning after a daemon restart; the daemon still rejects this while armed. */
  public configureMotion(): Promise<void> {
    return this.motion.configure(this.requireState().settings.motion);
  }

  /** Arms the motion daemon after its position has been established. */
  public arm(): Promise<void> {
    return this.motion.arm();
  }

  /** Disarms the machine and invalidates live execution until re-armed. */
  public disarm(): Promise<void> {
    return this.motion.disarm();
  }

  /** Clears a latched motion fault without establishing or arming position. */
  public reset(): Promise<void> {
    return this.motion.reset();
  }

  /** Establishes the visually aligned zero-based turret position. */
  public setPosition(slot: number): Promise<void> {
    return this.motion.setPosition(slot);
  }

  /** Performs a commissioning move outside the drink queue. */
  public move(slot: number): Promise<void> {
    if (this.activeJobId) {
      throw new DomainError("MACHINE_BUSY", "A drink job currently owns the machine");
    }
    return this.motion.move(slot);
  }

  /** Submits a fully preflighted immutable plan to the FIFO queue. */
  public async submitJob(recipeId: string): Promise<Job> {
    const state = this.requireState();
    const recipe = state.recipes.find((candidate) => candidate.id === recipeId);
    if (!recipe) {
      throw new DomainError("RECIPE_NOT_FOUND", `Recipe ${recipeId} was not found`);
    }
    const timestamp = this.timestamp();
    const job: Job = {
      id: randomUUID(),
      status: "queued",
      plan: buildDrinkPlan(recipe, this.activeInventory(), state.settings),
      currentStep: 0,
      createdAt: timestamp,
      updatedAt: timestamp,
      error: null,
    };
    state.jobs.push(job);
    state.jobs = state.jobs.slice(-100);
    await this.persist();
    void this.pump();
    return structuredClone(job);
  }

  /** Returns one retained job by identifier. */
  public getJob(jobId: string): Job {
    const job = this.requireState().jobs.find((candidate) => candidate.id === jobId);
    if (!job) {
      throw new DomainError("JOB_NOT_FOUND", `Job ${jobId} was not found`);
    }
    return structuredClone(job);
  }

  /** Acknowledges the currently displayed manual ingredient step. */
  public continueJob(jobId: string): Promise<Job> {
    const job = this.mutableJob(jobId);
    if (job.status !== "waiting_manual") {
      throw new DomainError("JOB_NOT_WAITING", "Job is not waiting for a manual step");
    }
    const waiter = this.manualWaiters.get(jobId);
    if (!waiter) {
      throw new DomainError("JOB_NOT_WAITING", "Manual acknowledgement is unavailable");
    }
    waiter.resolve(true);
    return Promise.resolve(this.getJob(jobId));
  }

  /** Cancels a queued or active job and stops live motion when necessary. */
  public async cancelJob(jobId: string): Promise<Job> {
    const job = this.mutableJob(jobId);
    if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") {
      return structuredClone(job);
    }
    job.status = "cancelled";
    job.error = "Cancelled by operator";
    job.updatedAt = this.timestamp();
    this.manualWaiters.get(jobId)?.resolve(false);
    await this.persist();
    if (this.activeJobId === jobId) {
      await this.motion.stop();
    }
    return structuredClone(job);
  }

  /** Cancels all pending work and triggers the daemon's out-of-band stop path. */
  public async stopMachine(): Promise<void> {
    const state = this.requireState();
    for (const job of state.jobs) {
      if (job.status === "queued" || job.status === "running" || job.status === "waiting_manual") {
        job.status = "cancelled";
        job.error = "Machine stopped by operator";
        job.updatedAt = this.timestamp();
        this.manualWaiters.get(job.id)?.resolve(false);
      }
    }
    await this.persist();
    await this.motion.stop();
  }

  private async pump(): Promise<void> {
    if (this.pumping) {
      return;
    }
    this.pumping = true;
    try {
      for (;;) {
        const job = this.requireState().jobs.find((candidate) => candidate.status === "queued");
        if (!job) {
          return;
        }
        await this.runJob(job);
      }
    } finally {
      this.pumping = false;
    }
  }

  private async runJob(job: Job): Promise<void> {
    this.activeJobId = job.id;
    let jobMotorActive = false;
    job.status = "running";
    job.updatedAt = this.timestamp();
    await this.persist();
    try {
      const status = await this.motion.status();
      if (!status.armed || status.position === null || status.state !== "ready") {
        throw new DomainError("MACHINE_NOT_READY", "Machine must be armed and positioned");
      }
      if (job.plan.stepOrder === "flexible") {
        job.plan = optimizeFlexiblePlan(job.plan, status.position);
        await this.persist();
      }
      for (let index = job.currentStep; index < job.plan.steps.length; index += 1) {
        const step = job.plan.steps[index];
        if (!step) {
          throw new DomainError("INVALID_PLAN", "Job plan contains a missing step");
        }
        if (this.jobCancelled(job.id)) {
          return;
        }
        if (step.kind === "manual") {
          if (jobMotorActive) {
            await this.motion.endJob();
            jobMotorActive = false;
          }
          job.status = "waiting_manual";
          job.updatedAt = this.timestamp();
          await this.persist();
          const proceed = await this.waitForManual(job.id);
          if (!proceed || this.jobCancelled(job.id)) {
            return;
          }
          job.status = "running";
        } else {
          if (!jobMotorActive) {
            await this.motion.beginJob();
            jobMotorActive = true;
          }
          await this.motion.move(step.slot, this.balanceAwareTimingPercent());
          await this.motion.dispense(step.pressCount, step.pressDurationMs, step.releaseDurationMs);
        }
        job.currentStep = index + 1;
        job.updatedAt = this.timestamp();
        await this.persist();
      }
      job.status = "completed";
      job.updatedAt = this.timestamp();
      await this.persist();
    } catch (error) {
      if (!this.jobCancelled(job.id)) {
        job.status = "failed";
        job.error = error instanceof Error ? error.message : "Unknown job failure";
        job.updatedAt = this.timestamp();
        await this.persist();
      }
    } finally {
      if (jobMotorActive) {
        await this.motion.endJob().catch(() => undefined);
      }
      this.manualWaiters.delete(job.id);
      this.activeJobId = null;
    }
  }

  private waitForManual(jobId: string): Promise<boolean> {
    return new Promise((resolve) => this.manualWaiters.set(jobId, { resolve }));
  }

  private mutableJob(jobId: string): Job {
    const job = this.requireState().jobs.find((candidate) => candidate.id === jobId);
    if (!job) {
      throw new DomainError("JOB_NOT_FOUND", `Job ${jobId} was not found`);
    }
    return job;
  }

  private jobCancelled(jobId: string): boolean {
    return this.mutableJob(jobId).status === "cancelled";
  }

  private requireState(): StateDocument {
    if (!this.state) {
      throw new DomainError("NOT_INITIALIZED", "BarRobot service is not initialized");
    }
    return this.state;
  }

  private activeInventory(): InventoryItem[] {
    const state = this.requireState();
    return state.inventoryProfiles[state.settings.productProfile];
  }

  /** Slows automatic work when the operator's fill estimates form a lopsided turret. */
  private balanceAwareTimingPercent(): number {
    const bottles = this.activeInventory().filter(
      (item) =>
        item.enabled &&
        item.mode === "bottle" &&
        item.slot !== null &&
        item.estimatedFillPercent !== null &&
        item.estimatedFillPercent > 0,
    );
    const total = bottles.reduce((sum, item) => sum + (item.estimatedFillPercent ?? 0), 0);
    if (total === 0) {
      return 100;
    }
    const vector = bottles.reduce(
      (result, item) => {
        const angle = ((item.slot ?? 0) / 12) * Math.PI * 2;
        const load = item.estimatedFillPercent ?? 0;
        return { x: result.x + Math.cos(angle) * load, y: result.y + Math.sin(angle) * load };
      },
      { x: 0, y: 0 },
    );
    const imbalance = Math.hypot(vector.x, vector.y) / total;
    return imbalance >= 0.65 ? 150 : imbalance >= 0.4 ? 125 : 100;
  }

  private persist(): Promise<void> {
    return this.repository.save(this.requireState());
  }

  private timestamp(): string {
    return this.now().toISOString();
  }
}
