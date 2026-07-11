"""Thread-safe turret and actuator control."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager

from .config import DEFAULT_PIN_MAP, TOTAL_SLOTS
from .gpio import GpioAdapter, RaspberryPiGpioAdapter

STEPS_PER_REV = 200
MICROSTEP = 8
TOTAL_MICROSTEPS = STEPS_PER_REV * MICROSTEP
STEP_DELAY_SEC = 0.0012
PUSH_DURATION_MS = 600


class HardwareError(RuntimeError):
    """Raised when GPIO initialization or hardware movement fails."""


class PositionUnknownError(HardwareError):
    """Raised when live movement is requested before position is established."""


class HardwareController:
    """Own GPIO state, logical turret position, and serialized operations."""

    def __init__(
        self,
        pin_map: Mapping[str, int] | None = None,
        safe_mode: bool = False,
        gpio: GpioAdapter | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._pin_map = dict(DEFAULT_PIN_MAP if pin_map is None else pin_map)
        self._safe_mode = bool(safe_mode)
        self._gpio = gpio
        self._sleeper = sleeper
        self._gpio_ready = False
        self._current_slot: int | None = 0 if self._safe_mode else None
        self._lock = threading.RLock()

    @property
    def safe_mode(self) -> bool:
        """Return whether the controller suppresses all GPIO output."""
        return self._safe_mode

    @property
    def current_slot(self) -> int | None:
        """Return the trusted zero-based slot, or None when position is unknown."""
        return self._current_slot

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Hold the hardware lock across a complete multi-action drink plan."""
        with self._lock:
            yield

    def set_pin_map(self, new_map: Mapping[str, int]) -> None:
        """Replace the runtime GPIO map after safely releasing old pins."""
        with self._lock:
            if dict(new_map) == self._pin_map:
                return
            self.cleanup()
            self._pin_map = {key.upper(): int(value) for key, value in new_map.items()}

    def set_safe_mode(self, enabled: bool) -> None:
        """Enable dry runs or require a fresh position when returning to live mode."""
        with self._lock:
            enabled = bool(enabled)
            if enabled and not self._safe_mode:
                self.cleanup()
            if not enabled and self._safe_mode:
                self._current_slot = None
            self._safe_mode = enabled
            if enabled and self._current_slot is None:
                self._current_slot = 0

    def establish_position(self, slot: int) -> None:
        """Trust the operator-supplied current physical slot without movement."""
        self._validate_slot(slot)
        with self._lock:
            self._current_slot = slot

    def rotate_to_slot(self, slot: int) -> None:
        """Rotate by the shortest slot path using acceleration and deceleration."""
        self._validate_slot(slot)
        with self._lock:
            if self._current_slot is None:
                raise PositionUnknownError(
                    "Turret position is unknown; align it and establish a slot in Motor Controls"
                )
            if slot == self._current_slot:
                return

            clockwise_slots = (slot - self._current_slot) % TOTAL_SLOTS
            counterclockwise_slots = (self._current_slot - slot) % TOTAL_SLOTS
            clockwise = clockwise_slots <= counterclockwise_slots

            if self._safe_mode:
                self._current_slot = slot
                return

            self._ensure_gpio()
            total_steps = self._movement_steps(self._current_slot, slot, clockwise)
            try:
                self._rotate_with_ramp(clockwise, total_steps)
            except HardwareError:
                self._current_slot = None
                self.cleanup()
                raise
            self._current_slot = slot

    def press_actuator(self, repetitions: int = 1) -> None:
        """Press the bottle valve the requested non-negative number of times."""
        if repetitions < 0:
            raise ValueError("repetitions cannot be negative")
        with self._lock:
            if self._safe_mode or repetitions == 0:
                return
            self._ensure_gpio()
            for _ in range(repetitions):
                self._output("ACTUATOR", True)
                self._sleeper(PUSH_DURATION_MS / 1000)
                self._output("ACTUATOR", False)
                self._sleeper(0.2)

    def cleanup(self) -> None:
        """Disable the driver when initialized and release GPIO resources."""
        with self._lock:
            if not self._gpio_ready or self._gpio is None:
                return
            try:
                self._output("ACTUATOR", False)
                self._output("ENABLE", True)
            finally:
                self._gpio.cleanup()
                self._gpio_ready = False

    def _ensure_gpio(self) -> None:
        """Initialize GPIO only immediately before the first live operation."""
        if self._safe_mode or self._gpio_ready:
            return
        try:
            if self._gpio is None:
                self._gpio = RaspberryPiGpioAdapter()
            self._gpio.setup_outputs(self._pin_map.values())
            self._output("ACTUATOR", False)
            self._output("ENABLE", False)
            self._gpio_ready = True
        except Exception as exc:
            self._gpio_ready = False
            raise HardwareError(f"Unable to initialize GPIO: {exc}") from exc

    def _rotate_with_ramp(self, clockwise: bool, total_steps: int) -> None:
        """Emit step pulses with the legacy conservative speed ramp."""
        ramp_steps = min(25, total_steps // 2)
        start_delay = STEP_DELAY_SEC * 5.0
        self._output("DIR", clockwise)
        try:
            for step in range(total_steps):
                delay = self._step_delay(step, total_steps, ramp_steps, start_delay)
                self._output("STEP", True)
                self._sleeper(delay)
                self._output("STEP", False)
                self._sleeper(delay)
        except Exception as exc:
            try:
                self._output("STEP", False)
            finally:
                raise HardwareError(f"Turret rotation failed: {exc}") from exc

    @staticmethod
    def _step_delay(step: int, total_steps: int, ramp_steps: int, start_delay: float) -> float:
        """Calculate one pulse delay while avoiding division for tiny moves."""
        if ramp_steps == 0:
            return STEP_DELAY_SEC
        if step < ramp_steps:
            progress = step / ramp_steps
            return start_delay - (start_delay - STEP_DELAY_SEC) * progress
        if step >= total_steps - ramp_steps:
            remaining = total_steps - step
            progress = remaining / ramp_steps
            return start_delay - (start_delay - STEP_DELAY_SEC) * progress
        return STEP_DELAY_SEC

    @staticmethod
    def _movement_steps(current: int, target: int, clockwise: bool) -> int:
        """Distribute indivisible microsteps across absolute slot boundaries."""
        positions = [round(index * TOTAL_MICROSTEPS / TOTAL_SLOTS) for index in range(TOTAL_SLOTS)]
        if clockwise:
            return (positions[target] - positions[current]) % TOTAL_MICROSTEPS
        return (positions[current] - positions[target]) % TOTAL_MICROSTEPS

    def _output(self, signal: str, high: bool) -> None:
        """Write a named signal through the configured GPIO adapter."""
        if self._gpio is None:
            raise HardwareError("GPIO adapter is not initialized")
        self._gpio.output(self._pin_map[signal], high)

    @staticmethod
    def _validate_slot(slot: int) -> None:
        """Validate a zero-based physical turret slot."""
        if not 0 <= slot < TOTAL_SLOTS:
            raise ValueError(f"slot must be from 0 through {TOTAL_SLOTS - 1}")
