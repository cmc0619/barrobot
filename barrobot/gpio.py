"""GPIO adapter boundary for Raspberry Pi and test environments."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class GpioAdapter(Protocol):
    """GPIO operations required by the hardware controller."""

    def setup_outputs(self, pins: Iterable[int]) -> None: ...
    def output(self, pin: int, high: bool) -> None: ...
    def cleanup(self) -> None: ...


class RaspberryPiGpioAdapter:
    """Lazy RPi.GPIO adapter that imports hardware support only when needed."""

    def __init__(self) -> None:
        try:
            import RPi.GPIO as gpio  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "RPi.GPIO is unavailable; enable safe mode or install Raspberry Pi GPIO support"
            ) from exc
        self._gpio = gpio

    def setup_outputs(self, pins: Iterable[int]) -> None:
        """Configure the supplied BCM pins as outputs."""
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setup(list(pins), self._gpio.OUT)

    def output(self, pin: int, high: bool) -> None:
        """Set one output pin high or low."""
        self._gpio.output(pin, self._gpio.HIGH if high else self._gpio.LOW)

    def cleanup(self) -> None:
        """Release all GPIO resources owned by this process."""
        self._gpio.cleanup()
