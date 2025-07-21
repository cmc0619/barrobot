"""
hardware.py
===========

All low-level helpers for the bar-robot:

• Turret rotation via DM542T-driven stepper motor  
• Push-actuator that presses the bottle valve  
• Runtime-configurable GPIO pin map + safe-mode

─────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import time
from typing import Dict

# -------------------------------------------------------------------
# GPIO import – mock on non-Pi machines so code still runs on a laptop
# -------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
except ModuleNotFoundError:                   # dev box / CI runner
    class _MockGPIO:                          # pylint: disable=too-few-public-methods
        BCM = "BCM"
        OUT = "OUT"
        HIGH = True
        LOW = False
        def setmode(self, *_):  ...
        def setup(self, *_):    ...
        def output(self, *_):   ...
        def cleanup(self):      ...
    GPIO = _MockGPIO()                         # type: ignore


# -------------------------------------------------------------------
# Motion constants (adjust as needed)
# -------------------------------------------------------------------
TOTAL_SLOTS      = 12          # turret positions
STEPS_PER_REV    = 200         # 1.8 ° motor
MICROSTEP        = 8
STEPS_PER_SLOT   = int((STEPS_PER_REV * MICROSTEP) / TOTAL_SLOTS)

STEP_DELAY_SEC   = 0.0008      # 800 µs between pulses
PUSH_DURATION_MS = 600         # valve-press time (≈ 1 oz)

# -------------------------------------------------------------------
# Pin map – can be changed at runtime via set_pin_map()
# -------------------------------------------------------------------
_pin_map: Dict[str, int] = {
    "DIR":      20,
    "STEP":     21,
    "ENABLE":   16,   # low-active on most DM542T variants
    "ACTUATOR": 26,
}

# -------------------------------------------------------------------
# Globals
# -------------------------------------------------------------------
SAFE_MODE   = True
_current_slot = 0
_gpio_ready   = False

# -------------------------------------------------------------------
# Pin-map management
# -------------------------------------------------------------------
def set_pin_map(new_map: Dict[str, int]) -> None:
    """
    Update the GPIO mapping (e.g. after user changes it in the UI).

    Accepts any subset of {"DIR","STEP","ENABLE","ACTUATOR"}.
    """
    global _pin_map, _gpio_ready
    # Clean up existing setup so next use re-initialises with new pins
    if _gpio_ready:
        GPIO.cleanup()
        _gpio_ready = False

    _pin_map.update({k.upper(): int(v) for k, v in new_map.items() if k})
    print(f"[HARDWARE] Pin map updated → {_pin_map}")


# -------------------------------------------------------------------
# GPIO setup / teardown helpers
# -------------------------------------------------------------------
def _ensure_gpio():
    """Initialise GPIO the first time we actually drive hardware."""
    global _gpio_ready
    if _gpio_ready or SAFE_MODE:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(list(_pin_map.values()), GPIO.OUT)
    GPIO.output(_pin_map["ENABLE"], GPIO.LOW)   # enable motor
    _gpio_ready = True


def cleanup() -> None:
    if _gpio_ready:
        GPIO.output(_pin_map["ENABLE"], GPIO.HIGH)
        GPIO.cleanup()


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------
def set_safe_mode(enabled: bool) -> None:
    global SAFE_MODE
    SAFE_MODE = enabled
    print(f"[HARDWARE] Safe-mode {'ON' if enabled else 'OFF'}")


def rotate_to_slot(slot: int) -> None:
    """Shortest-path CW rotation to the requested turret slot."""
    global _current_slot

    if slot == _current_slot:
        return

    if SAFE_MODE:
        print(f"[SAFE] Would rotate slot {_current_slot} → {slot}")
        _current_slot = slot
        return

    _ensure_gpio()

    delta  = (slot - _current_slot) % TOTAL_SLOTS           # CW positive
    steps  = delta * STEPS_PER_SLOT

    GPIO.output(_pin_map["DIR"], GPIO.HIGH)                 # CW
    for _ in range(steps):
        GPIO.output(_pin_map["STEP"], GPIO.HIGH)
        time.sleep(STEP_DELAY_SEC)
        GPIO.output(_pin_map["STEP"], GPIO.LOW)
        time.sleep(STEP_DELAY_SEC)

    _current_slot = slot
    print(f"[HARDWARE] Rotated to slot {slot}")


def press_actuator(repetitions: int = 1) -> None:
    """Push the valve several times; ≈ 1 oz per press (calibrate as needed)."""
    if SAFE_MODE:
        print(f"[SAFE] Would press actuator ×{repetitions}")
        return

    _ensure_gpio()

    for i in range(repetitions):
        GPIO.output(_pin_map["ACTUATOR"], GPIO.HIGH)
        time.sleep(PUSH_DURATION_MS / 1000)
        GPIO.output(_pin_map["ACTUATOR"], GPIO.LOW)
        time.sleep(0.2)
        print(f"[HARDWARE] Actuator press {i + 1}/{repetitions}")

