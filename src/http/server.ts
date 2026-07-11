import fastifyStatic from "@fastify/static";
import Fastify, { type FastifyInstance } from "fastify";
import { DomainError } from "../domain/errors.js";
import { MotionError } from "../adapters/motion-socket-client.js";
import { validateInventory, validateSettings } from "../adapters/state-validation.js";
import type { BarRobotService } from "../application/barrobot-service.js";

export interface HttpServerDependencies {
  service: BarRobotService;
  webRoot: string;
}

/** Builds the schema-bound HTTP API and same-origin touchscreen application. */
export async function buildHttpServer(
  dependencies: HttpServerDependencies,
): Promise<FastifyInstance> {
  const server = Fastify({ logger: true, bodyLimit: 1_000_000 });
  const { service } = dependencies;

  server.addHook("onRequest", (request, reply, done) => {
    if (request.method === "GET" || request.method === "HEAD" || !request.headers.origin) {
      done();
      return;
    }
    try {
      if (new URL(request.headers.origin).host !== request.headers.host) {
        void reply
          .code(403)
          .send({ error: "ORIGIN_DENIED", message: "Cross-origin request denied" });
        return;
      }
    } catch {
      void reply.code(403).send({ error: "ORIGIN_DENIED", message: "Invalid request origin" });
      return;
    }
    done();
  });

  server.get("/api/status", async () => {
    const state = service.snapshot();
    try {
      return {
        motion: await service.status(),
        queuedJobs: state.jobs.filter((job) => job.status === "queued").length,
        activeJob:
          state.jobs.find((job) => job.status === "running" || job.status === "waiting_manual") ??
          null,
      };
    } catch (error) {
      return {
        motion: {
          state: "offline",
          armed: false,
          position: null,
          realtime: false,
          error: error instanceof Error ? error.message : "Motion service offline",
        },
        queuedJobs: 0,
        activeJob: null,
      };
    }
  });

  server.get("/api/menu", () => service.menu());
  server.get("/api/recipes", () => service.snapshot().recipes);
  server.post("/api/recipes/sync", async (_request, reply) =>
    reply.code(200).send(await service.synchronizeRecipes()),
  );

  server.get("/api/inventory", () => service.snapshot().inventory);
  server.put("/api/inventory", async (request) => {
    validateInventory(request.body);
    return service.replaceInventory(request.body);
  });

  server.get("/api/settings", () => service.snapshot().settings);
  server.put("/api/settings", async (request) => {
    validateSettings(request.body);
    return service.replaceSettings(request.body);
  });

  server.post("/api/machine/arm", async (_request, reply) => {
    await service.arm();
    return reply.code(204).send();
  });
  server.post("/api/machine/disarm", async (_request, reply) => {
    await service.disarm();
    return reply.code(204).send();
  });
  server.post("/api/machine/reset", async (_request, reply) => {
    await service.reset();
    return reply.code(204).send();
  });
  server.post("/api/machine/position", async (request, reply) => {
    const slot = requireSlot(request.body);
    await service.setPosition(slot);
    return reply.code(204).send();
  });
  server.post("/api/machine/move", async (request, reply) => {
    const slot = requireSlot(request.body);
    await service.move(slot);
    return reply.code(204).send();
  });
  server.post("/api/machine/stop", async (_request, reply) => {
    await service.stopMachine();
    return reply.code(204).send();
  });

  server.post("/api/jobs", async (request, reply) => {
    const recipeId = requireStringField(request.body, "recipeId");
    return reply.code(202).send(await service.submitJob(recipeId));
  });
  server.get<{ Params: { id: string } }>("/api/jobs/:id", (request) =>
    service.getJob(request.params.id),
  );
  server.post<{ Params: { id: string } }>("/api/jobs/:id/continue", async (request) =>
    service.continueJob(request.params.id),
  );
  server.post<{ Params: { id: string } }>("/api/jobs/:id/cancel", async (request) =>
    service.cancelJob(request.params.id),
  );

  server.setErrorHandler((error, _request, reply) => {
    if (error instanceof DomainError) {
      const status = error.code.endsWith("NOT_FOUND") ? 404 : 400;
      return reply.code(status).send({ error: error.code, message: error.message });
    }
    if (error instanceof MotionError) {
      const status = error.code === "ENOENT" || error.code === "ECONNREFUSED" ? 503 : 409;
      return reply.code(status).send({ error: error.code, message: error.message });
    }
    server.log.error(error);
    return reply.code(500).send({ error: "INTERNAL", message: "Internal server error" });
  });

  await server.register(fastifyStatic, { root: dependencies.webRoot, prefix: "/" });
  server.setNotFoundHandler((request, reply) => {
    if (request.url.startsWith("/api/")) {
      return reply.code(404).send({ error: "NOT_FOUND", message: "API route not found" });
    }
    return reply.sendFile("index.html");
  });
  return server;
}

function requireSlot(body: unknown): number {
  if (!isRecord(body) || typeof body.slot !== "number" || !Number.isInteger(body.slot)) {
    throw new DomainError("INVALID_SLOT", "slot must be an integer");
  }
  if (body.slot < 0 || body.slot >= 12) {
    throw new DomainError("INVALID_SLOT", "slot must be from 0 through 11");
  }
  return body.slot;
}

function requireStringField(body: unknown, field: string): string {
  if (!isRecord(body) || typeof body[field] !== "string" || body[field].length === 0) {
    throw new DomainError("INVALID_REQUEST", `${field} must be a non-empty string`);
  }
  return body[field];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
