import assert from "node:assert/strict";
import { resolve } from "node:path";
import { describe, it } from "node:test";
import { BarRobotService } from "../src/application/barrobot-service.js";
import { buildHttpServer } from "../src/http/server.js";
import { createDefaultState } from "../src/domain/seed.js";
import { FakeMotionController, FakeRecipeSource, MemoryStateRepository } from "./helpers.js";

describe("HTTP API", () => {
  it("exposes health while forbidding movement through GET", async () => {
    const motion = new FakeMotionController();
    const service = new BarRobotService(
      new MemoryStateRepository(createDefaultState()),
      motion,
      new FakeRecipeSource(),
    );
    await service.initialize();
    const server = await buildHttpServer({ service, webRoot: resolve("web") });
    const status = await server.inject({ method: "GET", url: "/api/status" });
    assert.equal(status.statusCode, 200);
    assert.equal(status.json().motion.state, "ready");
    const getMove = await server.inject({ method: "GET", url: "/api/machine/move" });
    assert.equal(getMove.statusCode, 404);
    assert.equal(motion.calls.includes("move:2"), false);
    const postMove = await server.inject({
      method: "POST",
      url: "/api/machine/move",
      payload: { slot: 2 },
    });
    assert.equal(postMove.statusCode, 204);
    assert.equal(motion.calls.includes("move:2"), true);
    await server.close();
  });

  it("rejects invalid slot input at the HTTP boundary", async () => {
    const service = new BarRobotService(
      new MemoryStateRepository(createDefaultState()),
      new FakeMotionController(),
      new FakeRecipeSource(),
    );
    await service.initialize();
    const server = await buildHttpServer({ service, webRoot: resolve("web") });
    const response = await server.inject({
      method: "POST",
      url: "/api/machine/position",
      payload: { slot: 12 },
    });
    assert.equal(response.statusCode, 400);
    assert.equal(response.json().error, "INVALID_SLOT");
    await server.close();
  });

  it("rejects cross-origin machine commands", async () => {
    const motion = new FakeMotionController();
    const service = new BarRobotService(
      new MemoryStateRepository(createDefaultState()),
      motion,
      new FakeRecipeSource(),
    );
    await service.initialize();
    const server = await buildHttpServer({ service, webRoot: resolve("web") });
    const response = await server.inject({
      method: "POST",
      url: "/api/machine/stop",
      headers: { origin: "https://evil.example", host: "barrobot.local:5000" },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(motion.calls.includes("stop"), false);
    await server.close();
  });
});
