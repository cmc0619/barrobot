![BarRobot](barrobot.jpg)

# BarRobot 🍸🤖

An open-source, 12-bottle cocktail turret: a Raspberry Pi rotates bottles over a
glass and presses each bottle's valve to pour a measured drink.

This repository holds **three complete implementations** of the controller, each
in its own directory. They are independent — pick one, install it, and ignore
the others. The hardware is the same for all three.

| | Directory | Stack | Status |
| --- | --- | --- | --- |
| **v1** | [`v1/`](v1/) | Python 3, Flask, single module | The original. Kept for reference. |
| **v2** | [`v2/`](v2/) | Python 3, Flask, layered services | A safety and testability rewrite of v1. Same pages and URLs. |
| **v3** | [`v3/`](v3/) | Node.js 24, TypeScript, Fastify, native C motion daemon | A greenfield rebuild. New UI, new API, new hardware boundary. |

## Which one should I use?

- **Start with [v3](v3/)** if you are building the machine now. It keeps GPIO in
  a dedicated C daemon, refuses to move until an operator establishes the
  turret's position, plans a drink completely before pouring it, and pauses for
  ingredients it cannot dispense instead of guessing.
- **Use [v2](v2/)** if you want the original Flask UI with the safety fixes: full
  recipe preflight, serialized hardware operations, trusted-position handling,
  and a test suite that runs without a Pi.
- **Use [v1](v1/)** only to see where the project started.

Each directory has its own README with hardware notes, install steps, and
screenshots of that version's UI.

## What they look like

### v1 — the original Flask menu

[![v1 menu](v1/docs/screenshots/menu.png)](v1/README.md)

### v2 — same pages, tightened up

[![v2 pour status list](v2/docs/screenshots/pour-v2.png)](v2/README.md)

### v3 — new touchscreen console

[![v3 machine tab](v3/docs/screenshots/dashboard-v3.png)](v3/README.md)

## Hardware

All three drive the same build: a Raspberry Pi, a 24 V supply, a DM542T driver
and NEMA-17 stepper turning a 12-slot turret, and a linear actuator that presses
the bottle valves. Full bills of materials are in the version READMEs.

Because the turret has no home switch, every version requires the operator to
align it physically and establish its slot before any live movement.

## Repository layout

```
v1/   original Flask application
v2/   Flask rewrite, with pytest suite
v3/   TypeScript application plus the C motion daemon
```

Continuous integration runs per directory: `.github/workflows/ci-v2.yml` and
`ci-v3.yml` only fire when their own version changes.

## License

[MIT](LICENSE) © 2025–2026 Cliff Campbell
