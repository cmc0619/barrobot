import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { BarRobotService } from "./application/barrobot-service.js";
import { CocktailDbSource } from "./adapters/cocktaildb-source.js";
import { JsonStateRepository } from "./adapters/json-state-repository.js";
import { MotionSocketClient } from "./adapters/motion-socket-client.js";
import { buildHttpServer } from "./http/server.js";

const statePath = resolve(process.env.BARROBOT_STATE_PATH ?? "data/state.json");
const repository = new JsonStateRepository(statePath);
const serviceReference: { current?: BarRobotService } = {};
const motion = new MotionSocketClient(
  () =>
    process.env.BARROBOT_MOTION_SOCKET ??
    serviceReference.current?.snapshot().settings.motionSocket ??
    "/run/barrobot/motion.sock",
);
const service = new BarRobotService(repository, motion, new CocktailDbSource());
serviceReference.current = service;
await service.initialize();

const settings = service.snapshot().settings;
const webRoot = fileURLToPath(new URL("../web", import.meta.url));
const server = await buildHttpServer({ service, webRoot });
const host = process.env.BARROBOT_HOST ?? settings.listenHost;
const port = Number(process.env.BARROBOT_PORT ?? settings.listenPort);

const shutdown = async (signal: string): Promise<void> => {
  server.log.info({ signal }, "Shutting down BarRobot");
  await server.close();
  process.exitCode = 0;
};

process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));

await server.listen({ host, port });
