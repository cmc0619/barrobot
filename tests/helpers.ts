import type {
  MotionController,
  MotionStatus,
  RecipeSource,
  StateRepository,
} from "../src/application/ports.js";
import type { MotionSettings, Recipe, StateDocument } from "../src/domain/model.js";

/** Provides isolated in-memory persistence for application tests. */
export class MemoryStateRepository implements StateRepository {
  public saves = 0;

  public constructor(public state: StateDocument) {}

  public load(): Promise<StateDocument> {
    return Promise.resolve(structuredClone(this.state));
  }

  public save(state: StateDocument): Promise<void> {
    this.saves += 1;
    this.state = structuredClone(state);
    return Promise.resolve();
  }
}

/** Records machine commands without touching GPIO or sockets. */
export class FakeMotionController implements MotionController {
  public calls: string[] = [];
  public machineStatus: MotionStatus = {
    state: "ready",
    armed: true,
    position: 0,
    realtime: true,
  };

  public status(): Promise<MotionStatus> {
    this.calls.push("status");
    return Promise.resolve(structuredClone(this.machineStatus));
  }

  public arm(): Promise<void> {
    this.calls.push("arm");
    this.machineStatus.armed = true;
    this.machineStatus.state = "ready";
    return Promise.resolve();
  }

  public disarm(): Promise<void> {
    this.calls.push("disarm");
    this.machineStatus.armed = false;
    this.machineStatus.state = "disarmed";
    return Promise.resolve();
  }

  public reset(): Promise<void> {
    this.calls.push("reset");
    this.machineStatus = { state: "disarmed", armed: false, position: null, realtime: true };
    return Promise.resolve();
  }

  public setPosition(slot: number): Promise<void> {
    this.calls.push(`position:${slot}`);
    this.machineStatus.position = slot;
    return Promise.resolve();
  }

  public move(slot: number): Promise<void> {
    this.calls.push(`move:${slot}`);
    this.machineStatus.position = slot;
    return Promise.resolve();
  }

  public dispense(
    pressCount: number,
    pressDurationMs: number,
    releaseDurationMs: number,
  ): Promise<void> {
    this.calls.push(`dispense:${pressCount}:${pressDurationMs}:${releaseDurationMs}`);
    return Promise.resolve();
  }

  public configure(settings: MotionSettings): Promise<void> {
    this.calls.push(`configure:${settings.rampSteps}`);
    return Promise.resolve();
  }

  public beginJob(): Promise<void> {
    this.calls.push("beginJob");
    return Promise.resolve();
  }

  public endJob(): Promise<void> {
    this.calls.push("endJob");
    return Promise.resolve();
  }

  public stop(): Promise<void> {
    this.calls.push("stop");
    this.machineStatus = { state: "fault", armed: false, position: null, realtime: true };
    return Promise.resolve();
  }
}

/** Returns a fixed catalogue for explicit recipe synchronization tests. */
export class FakeRecipeSource implements RecipeSource {
  public constructor(private readonly recipes: Recipe[] = []) {}

  public fetchAll(_apiKey: string): Promise<Recipe[]> {
    return Promise.resolve(structuredClone(this.recipes));
  }
}

/** Waits until an asynchronous state transition becomes observable. */
export async function waitFor(predicate: () => boolean, timeoutMs = 1_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) {
      throw new Error("Timed out waiting for condition");
    }
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}
