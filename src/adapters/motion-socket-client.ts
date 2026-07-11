import { createConnection } from "node:net";
import type { MotionController, MotionStatus } from "../application/ports.js";

/** Maps stable motion-service error responses to application errors. */
export class MotionError extends Error {
  public constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "MotionError";
  }
}

/** Controls the native GPIO daemon over one-request Unix socket connections. */
export class MotionSocketClient implements MotionController {
  public constructor(
    private readonly socketPath: () => string,
    private readonly timeoutMs = 120_000,
  ) {}

  public async status(): Promise<MotionStatus> {
    const fields = await this.command("STATUS", 2_000);
    const state = fields.state;
    if (state !== "disarmed" && state !== "ready" && state !== "busy" && state !== "fault") {
      throw new MotionError("PROTOCOL", "Motion service returned an invalid state");
    }
    return {
      state,
      armed: fields.armed === "1",
      position: fields.position === "unknown" ? null : Number(fields.position),
      realtime: fields.realtime === "1",
    };
  }

  public async arm(): Promise<void> {
    await this.command("ARM");
  }

  public async disarm(): Promise<void> {
    await this.command("DISARM");
  }

  public async reset(): Promise<void> {
    await this.command("RESET");
  }

  public async setPosition(slot: number): Promise<void> {
    await this.command(`SET_POSITION ${slot}`);
  }

  public async move(slot: number): Promise<void> {
    await this.command(`MOVE ${slot}`);
  }

  public async dispense(
    pressCount: number,
    pressDurationMs: number,
    releaseDurationMs: number,
  ): Promise<void> {
    await this.command(`DISPENSE ${pressCount} ${pressDurationMs} ${releaseDurationMs}`);
  }

  public async stop(): Promise<void> {
    await this.command("STOP", 2_000);
  }

  private command(command: string, timeoutMs = this.timeoutMs): Promise<Record<string, string>> {
    return new Promise((resolve, reject) => {
      const socket = createConnection(this.socketPath());
      let response = "";
      const fail = (error: Error): void => {
        socket.destroy();
        reject(error);
      };
      socket.setEncoding("utf8");
      socket.setTimeout(timeoutMs, () => fail(new MotionError("TIMEOUT", `${command} timed out`)));
      socket.on("connect", () => socket.end(`${command}\n`));
      socket.on("data", (chunk: string) => {
        response += chunk;
        if (response.length > 4096) {
          fail(new MotionError("PROTOCOL", "Motion response exceeded 4096 bytes"));
        }
      });
      socket.on("error", (error) => {
        const code = "code" in error && typeof error.code === "string" ? error.code : "SOCKET";
        fail(new MotionError(code, error.message));
      });
      socket.on("end", () => {
        try {
          resolve(parseResponse(response));
        } catch (error) {
          reject(error instanceof Error ? error : new Error(String(error)));
        }
      });
    });
  }
}

function parseResponse(raw: string): Record<string, string> {
  const line = raw.trim();
  if (line.startsWith("ERR ")) {
    const [, code = "UNKNOWN", ...message] = line.split(" ");
    throw new MotionError(code, message.join(" ") || code);
  }
  if (line !== "OK" && !line.startsWith("OK ")) {
    throw new MotionError("PROTOCOL", `Unexpected motion response: ${line}`);
  }
  return Object.fromEntries(
    line
      .slice(2)
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .map((field) => {
        const separator = field.indexOf("=");
        return separator === -1
          ? [field, "1"]
          : [field.slice(0, separator), field.slice(separator + 1)];
      }),
  );
}

/** Parses one motion response for protocol-focused tests and diagnostics. */
export function parseMotionResponse(raw: string): Record<string, string> {
  return parseResponse(raw);
}
