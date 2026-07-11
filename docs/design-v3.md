# BarRobot v3 Greenfield Design

## Decision

BarRobot v3 is a new application for the existing Raspberry Pi, DM542T stepper
driver, NEMA-17 motor, 12-position turret, and actuator. It does not preserve
v1/v2 routes, configuration files, recipe cache, module boundaries, or runtime
behavior.

The system has two local processes:

1. **BarRobot application:** TypeScript on Node.js 24 LTS. It owns the web UI,
   HTTP API, recipe catalogue, inventory, planning, persistence, and job queue.
2. **Motion service:** C11 on Linux. It exclusively owns the existing GPIO
   lines, step timing, actuator timing, logical turret position, and emergency
   stop state.

The processes communicate through a root-owned Unix domain socket. The web
process never opens a GPIO device and the motion process never parses HTTP.

## Why this stack

- Node.js 24 is an active LTS release for the Pi and has first-class TypeScript
  tooling, fetch, testing, and structured concurrency.
- Fastify provides a small, schema-driven HTTP boundary without imposing a
  front-end framework.
- The Linux GPIO character-device API is the maintained replacement for GPIO
  sysfs and works across current Raspberry Pi kernels.
- C can request the GPIO lines once, schedule pulses against
  `CLOCK_MONOTONIC`, use absolute deadlines to avoid accumulated timer drift,
  and run the motion thread with optional real-time scheduling.
- Process isolation means an application crash closes its socket but does not
  transfer GPIO ownership or leave two runtimes fighting over pins.

## Hardware contract

v3 assumes the already-purchased hardware and does not add a microcontroller,
home switch, E-stop switch, encoder, or different driver.

Default BCM assignments remain configurable:

| Signal    | Default BCM line | Behavior                           |
| --------- | ---------------: | ---------------------------------- |
| Direction |               20 | High for clockwise                 |
| Step      |               21 | Rising edge advances one microstep |
| Enable    |               16 | Active low                         |
| Actuator  |               26 | Active high                        |

The GPIO chip path defaults to `/dev/gpiochip0`. It is configuration rather than
an assumption because Raspberry Pi kernel/device-tree layouts can expose header
GPIO on a different chip.

The motion service is built directly against the Linux GPIO v2 UAPI in
`<linux/gpio.h>` and has no retired Raspberry Pi GPIO library dependency.

## Safety model

The machine starts **disarmed** with the motor disabled, actuator low, and
position unknown. Live commands require all of the following:

- motion service healthy;
- application connected;
- operator explicitly armed the machine;
- operator established the physical turret position;
- no fault or stop is latched;
- a fully preflighted drink plan;
- no other active hardware job.

There is no fictional automatic homing. With no sensor in the purchased
hardware, the operator visually aligns the turret and establishes its current
slot. Any interrupted move, motion-process restart, GPIO error, timeout, or
emergency stop invalidates position and disarms the machine.

`POST /api/machine/stop` is handled on a separate motion-service connection and
sets an atomic stop flag. Motion checks that flag between every step pulse and
actuator phase. Software stop cannot provide the guarantees of a hardwired
E-stop, but it is implemented as promptly as the existing hardware permits.

## Motion timing

- 200 full steps/revolution and 8 microsteps are the defaults.
- Absolute slot boundaries are calculated over all 1,600 microsteps. The four
  indivisible remainder steps are distributed across the 12 slots.
- Direction uses the shortest slot distance; a six-slot tie is clockwise.
- Each move uses a symmetric cubic S-curve, with zero slope at launch and
  braking. This avoids the sharp initial jerk of a linear ramp.
- The daemon holds motor torque through the configured settle interval and
  actuator press when requested; disarm, stop, fault, and reset always release
  it.
- Pulse deadlines use `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, ...)` so
  syscall and scheduler latency does not accumulate into positional drift.
- The motion thread attempts `SCHED_FIFO` when allowed. Failure to obtain it is
  reported in status and logs but is not silently presented as real-time.
- The daemon never guesses the final slot after an interrupted move.

## Motion protocol

The Unix socket uses one UTF-8 line per connection and one response line. The
socket path defaults to `/run/barrobot/motion.sock`.

Commands:

```text
STATUS
ARM
DISARM
RESET
SET_POSITION <zero-based-slot>
CONFIGURE <ramp-steps> <min-half-period-us> <max-half-period-us> <settle-ms> <hold-0-or-1>
MOVE <zero-based-slot>
DISPENSE <press-count> <on-ms> <off-ms>
STOP
```

Responses:

```text
OK <key=value>...
ERR <stable-code> <human-readable-message>
```

Stable error codes include `INVALID`, `DISARMED`, `POSITION_UNKNOWN`, `BUSY`,
`STOPPED`, `GPIO`, and `INTERNAL`.

Each request uses a separate socket connection. Long motion commands hold the
hardware mutex, while `STOP` only sets the atomic stop flag and therefore does
not wait behind the active move.

## Application architecture

```text
src/
  domain/          Recipes, inventory, availability, and pour planning
  application/     Job queue and machine orchestration
  adapters/        Atomic JSON store, CocktailDB client, motion socket client
  http/            Fastify routes, schemas, and error mapping
  main.ts          Composition root and shutdown handling
web/               Framework-free touchscreen application
motiond/           Native GPIO daemon for the existing hardware
```

Domain code is pure TypeScript. External data is validated at adapters and HTTP
boundaries. The application layer depends on interfaces, not Fastify, files, or
sockets.

All TypeScript comments are JSDoc blocks. C public functions and protocol types
use Doxygen-compatible docblocks. Narrative inline comments are avoided; names
and extracted functions carry the implementation intent.

## Persistence model

The application stores one versioned JSON document using write-to-temp, fsync,
rename, and directory fsync:

```json
{
  "schemaVersion": 2,
  "settings": {
    "productProfile": "cocktail",
    "cocktailDbApiKey": "1",
    "motionSocket": "/run/barrobot/motion.sock",
    "maxDoseErrorPercent": 20,
    "motionProfile": "gentle",
    "motion": {
      "minimumHalfPeriodUs": 1300,
      "maximumHalfPeriodUs": 7000,
      "rampSteps": 120,
      "settleMs": 280,
      "holdPosition": true
    },
    "completionSound": "chime"
  },
  "inventory": [],
  "recipes": []
}
```

The file defaults to `/var/lib/barrobot/state.json`. A new installation seeds
an empty inventory and a small offline recipe catalogue; CocktailDB sync is an
explicit operator action, never a startup dependency.

### Inventory

Inventory is ingredient-centric rather than a loose array of strings:

- `id`: stable generated identifier;
- `name`: normalized display name;
- `aliases`: alternate recipe names;
- `mode`: `bottle` or `pantry`;
- `slot`: required and unique for a bottle;
- `mlPerPress`: calibrated output for that installed bottle;
- `enabled`: whether the item participates in planning.

### Recipes

- stable recipe ID and source;
- name, image, and instructions;
- ordered ingredients;
- quantity in milliliters when machine-readable;
- original measure text;
- explicit `manual` flag for garnish, ambiguous, or non-liquid measures.

Unknown measures remain manual. v3 does not invent a liquid quantity or scale a
recipe until its smallest ingredient happens to match a valve press.

## Planning

Planning completes before a job is accepted:

1. Resolve every ingredient against enabled inventory names and aliases.
2. Reject the recipe if any required item is absent.
3. Pantry, garnish, and ambiguous quantities become manual instructions.
4. Bottle quantities become calibrated press counts.
5. Calculate delivered volume and reject automatic doses whose error exceeds
   `maxDoseErrorPercent`.
6. Emit an immutable ordered plan and snapshot it into the job record.

Jobs run FIFO, one at a time. HTTP job creation returns `202 Accepted` with a
job ID. The UI polls job state and displays manual-add pauses. The operator
acknowledges a manual step before execution continues.

Job states are `queued`, `running`, `waiting_manual`, `completed`, `failed`, and
`cancelled`. A process restart marks any nonterminal job failed; it never
resumes a half-poured drink.

## HTTP API

All state-changing endpoints use JSON POST/PUT requests. No GET request can
move hardware.

```text
GET  /api/status
GET  /api/menu
GET  /api/recipes
POST /api/recipes/sync
GET  /api/inventory
PUT  /api/inventory
GET  /api/settings
PUT  /api/settings
POST /api/machine/arm
POST /api/machine/disarm
POST /api/machine/position
POST /api/machine/move
POST /api/machine/stop
POST /api/jobs
GET  /api/jobs/:id
POST /api/jobs/:id/continue
POST /api/jobs/:id/cancel
```

The server binds to loopback by default. LAN binding is explicit configuration.
The touchscreen UI is served from the same origin, and CORS is not enabled.

## Touchscreen UI

The UI is a small, dependency-free responsive application:

- dashboard with motion health, armed state, position, queue, and stop control;
- mutually-exclusive Cocktail maker / Slushie maker profile with a matching
  catalogue and visual theme;
- makeable product menu with search and recipe details;
- live job progress and manual-add acknowledgement;
- inventory editor with slot uniqueness and per-bottle calibration;
- machine commissioning page for arm/disarm, position establishment, and test
  moves;
- guarded motion profiles, optional completion chime, settings, and explicit
  CocktailDB synchronization.

It is designed for large touch targets and works without external assets after
installation.

## Deployment

Two hardened systemd units are installed:

- `barrobot-motion.service` starts first, owns GPIO, creates the socket, and
  receives only the capabilities needed for GPIO and optional real-time
  scheduling.
- `barrobot.service` starts afterward as an unprivileged user and accesses only
  its data directory and the motion socket.

The TypeScript application is compiled to JavaScript during release. Production
installation requires Node.js 24 LTS, the compiled application, static assets,
and the native `barrobot-motiond` binary. No compiler runs at service startup.

## Testing and CI

- domain tests cover normalization, aliasing, availability, calibration error,
  and immutable planning;
- application tests cover FIFO execution, manual pauses, cancellation, stop,
  and restart failure semantics;
- adapter tests cover atomic persistence, CocktailDB parsing, and socket
  protocol behavior;
- HTTP tests use Fastify injection and a fake motion controller;
- motion tests run against a fake GPIO backend and verify exact steps, ramp
  boundaries, interruption, disarming, and position invalidation;
- C compilation uses strict warnings and sanitizers on x86 CI;
- TypeScript uses strict mode, type checking, linting, formatting, and Node's
  built-in test runner;
- the application is cross-built for Linux ARM64 in CI.

## Deliberate exclusions

- no v1/v2 configuration migration;
- no legacy Flask routes or Python compatibility modules;
- no automatic update mechanism;
- no movement from HTTP GET;
- no assumed startup position;
- no recipe-wide arbitrary scaling;
- no direct GPIO access from Node;
- no dependency on an archived Raspberry Pi GPIO library;
- no claim of hard real-time or hardwired E-stop behavior from software alone.

## Acceptance criteria

- the web application and motion daemon build independently;
- all tests run without Raspberry Pi hardware or network access;
- safe output states are established before accepting commands;
- a fresh daemon starts disarmed with unknown position;
- exact step counts sum to one complete revolution;
- interruption disarms and invalidates position;
- one active job owns the machine while STOP remains out-of-band;
- unparseable recipe measures are manual, never guessed;
- state writes are atomic and versioned;
- systemd deployment uses the existing hardware without additional purchases;
- CI passes before the draft PR is handed over.
