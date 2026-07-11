import { open, readFile, rename } from "node:fs/promises";
import { dirname } from "node:path";
import { mkdir } from "node:fs/promises";
import type { StateDocument } from "../domain/model.js";
import { createDefaultState } from "../domain/seed.js";
import type { StateRepository } from "../application/ports.js";
import { validateStateDocument } from "./state-validation.js";

/** Persists one versioned state document with atomic replacement and fsync. */
export class JsonStateRepository implements StateRepository {
  private writeTail: Promise<void> = Promise.resolve();

  public constructor(private readonly path: string) {}

  public async load(): Promise<StateDocument> {
    try {
      const parsed: unknown = JSON.parse(await readFile(this.path, "utf8"));
      validateStateDocument(parsed);
      return structuredClone(parsed);
    } catch (error) {
      if (isMissingFile(error)) {
        const initial = createDefaultState();
        await this.save(initial);
        return initial;
      }
      throw error;
    }
  }

  public async save(state: StateDocument): Promise<void> {
    const snapshot = structuredClone(state);
    validateStateDocument(snapshot);
    const write = this.writeTail.then(() => this.writeAtomic(snapshot));
    this.writeTail = write.catch(() => undefined);
    return write;
  }

  private async writeAtomic(state: StateDocument): Promise<void> {
    const directory = dirname(this.path);
    const temporary = `${this.path}.${process.pid}.${Date.now()}.tmp`;
    await mkdir(directory, { recursive: true });
    const file = await open(temporary, "wx", 0o600);
    try {
      await file.writeFile(`${JSON.stringify(state, null, 2)}\n`, "utf8");
      await file.sync();
    } finally {
      await file.close();
    }
    await rename(temporary, this.path);
    const directoryHandle = await open(directory, "r");
    try {
      await directoryHandle.sync();
    } finally {
      await directoryHandle.close();
    }
  }
}

function isMissingFile(error: unknown): boolean {
  return error instanceof Error && "code" in error && error.code === "ENOENT";
}
