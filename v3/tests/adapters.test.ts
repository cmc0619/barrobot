import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import { JsonStateRepository } from "../src/adapters/json-state-repository.js";
import { MotionError, parseMotionResponse } from "../src/adapters/motion-socket-client.js";

describe("JsonStateRepository", () => {
  it("creates and atomically replaces a valid initial document", async () => {
    const directory = await mkdtemp(join(tmpdir(), "barrobot-state-"));
    const path = join(directory, "state.json");
    const repository = new JsonStateRepository(path);
    const state = await repository.load();
    state.settings.maxDoseErrorPercent = 12;
    await repository.save(state);
    const persisted = JSON.parse(await readFile(path, "utf8"));
    assert.equal(persisted.schemaVersion, 4);
    assert.equal(persisted.settings.maxDoseErrorPercent, 12);
  });

  it("rejects corrupt versioned state instead of replacing it", async () => {
    const directory = await mkdtemp(join(tmpdir(), "barrobot-state-"));
    const path = join(directory, "state.json");
    const payload =
      '{"schemaVersion":4,"settings":{},"inventoryProfiles":{},"recipes":[],"jobs":[]}';
    await writeFile(path, payload);
    const repository = new JsonStateRepository(path);
    await assert.rejects(repository.load(), /Settings contain invalid values/);
    assert.equal(await readFile(path, "utf8"), payload);
  });
});

describe("motion protocol", () => {
  it("parses status fields", () => {
    assert.deepEqual(parseMotionResponse("OK state=ready armed=1 position=4 realtime=1\n"), {
      state: "ready",
      armed: "1",
      position: "4",
      realtime: "1",
    });
  });

  it("maps stable error codes", () => {
    assert.throws(
      () => parseMotionResponse("ERR POSITION_UNKNOWN establish_position\n"),
      (error: unknown) => error instanceof MotionError && error.code === "POSITION_UNKNOWN",
    );
  });
});
