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

STEP_DELAY_SEC   = 0.0012      # 800 µs between pulses
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
SAFE_MODE   = False
_current_slot = 0
_gpio_ready   = True

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
    """Shortest-path rotation with acceleration/deceleration for bottle safety."""
    global _current_slot

    if slot == _current_slot:
        return

    # Calculate both directions
    cw_delta = (slot - _current_slot) % TOTAL_SLOTS
    ccw_delta = (_current_slot - slot) % TOTAL_SLOTS
    
    # Choose shortest path
    if cw_delta <= ccw_delta:
        clockwise = True
        delta = cw_delta
    else:
        clockwise = False
        delta = ccw_delta

    if SAFE_MODE:
        direction_str = "CW" if clockwise else "CCW"
        print(f"[SAFE] Would rotate slot {_current_slot} → {slot} ({direction_str}, {delta} slots)")
        _current_slot = slot
        return

    _ensure_gpio()

    total_steps = delta * STEPS_PER_SLOT
    
    # Always use ramping - inertia matters for any move with heavy bottles
    _rotate_with_ramp(clockwise, total_steps)

    _current_slot = slot
    direction_str = "CW" if clockwise else "CCW"
    print(f"[HARDWARE] Rotated {direction_str} to slot {slot} ({delta} slots)")


def _rotate_with_ramp(clockwise: bool, total_steps: int) -> None:
    """Rotate with acceleration/deceleration ramp for smooth bottle movement."""
    
    # Ramp parameters - very conservative for heavy 1.5L bottles
    ramp_steps = min(25, total_steps // 2)  # At least 25 steps ramp, or half the move
    start_delay = STEP_DELAY_SEC * 5.0      # Start 5x slower for heavy bottles
    cruise_delay = STEP_DELAY_SEC           # Normal speed for cruising
    
    GPIO.output(_pin_map["DIR"], GPIO.HIGH if clockwise else GPIO.LOW)
    
    for step in range(total_steps):
        if step < ramp_steps:
            # Acceleration phase - start slow, speed up
            progress = step / ramp_steps
            delay = start_delay - (start_delay - cruise_delay) * progress
        elif step >= total_steps - ramp_steps:
            # Deceleration phase - slow down to stop
            remaining = total_steps - step
            progress = remaining / ramp_steps
            delay = start_delay - (start_delay - cruise_delay) * progress
        else:
            # Cruise phase - constant speed
            delay = cruise_delay
        
        GPIO.output(_pin_map["STEP"], GPIO.HIGH)
        time.sleep(delay)
        GPIO.output(_pin_map["STEP"], GPIO.LOW)
        time.sleep(delay) 
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

