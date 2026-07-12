import type { MotionSettings, Recipe, StateDocument } from "../domain/model.js";

export interface MotionStatus {
  state: "disarmed" | "ready" | "busy" | "fault";
  armed: boolean;
  position: number | null;
  realtime: boolean;
}

export interface MotionController {
  status(): Promise<MotionStatus>;
  arm(): Promise<void>;
  disarm(): Promise<void>;
  reset(): Promise<void>;
  setPosition(slot: number): Promise<void>;
  move(slot: number, timingPercent?: number): Promise<void>;
  dispense(pressCount: number, pressDurationMs: number, releaseDurationMs: number): Promise<void>;
  configure(settings: MotionSettings): Promise<void>;
  beginJob(): Promise<void>;
  endJob(): Promise<void>;
  stop(): Promise<void>;
}

export interface StateRepository {
  load(): Promise<StateDocument>;
  save(state: StateDocument): Promise<void>;
}

export interface RecipeSource {
  fetchAll(apiKey: string): Promise<Recipe[]>;
}
