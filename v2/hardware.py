"""Backward-compatible module facade for BarRobot hardware helpers."""

from __future__ import annotations

from collections.abc import Mapping

from barrobot.hardware import HardwareController

_controller = HardwareController()


def set_pin_map(new_map: Mapping[str, int]) -> None:
    """Update GPIO pins on the compatibility controller."""
    _controller.set_pin_map(new_map)


def set_safe_mode(enabled: bool) -> None:
    """Update dry-run mode on the compatibility controller."""
    _controller.set_safe_mode(enabled)


def establish_position(slot: int) -> None:
    """Establish a zero-based physical slot without movement."""
    _controller.establish_position(slot)


def rotate_to_slot(slot: int) -> None:
    """Rotate the compatibility controller to a zero-based slot."""
    _controller.rotate_to_slot(slot)


def press_actuator(repetitions: int = 1) -> None:
    """Press the actuator through the compatibility controller."""
    _controller.press_actuator(repetitions)


def cleanup() -> None:
    """Release GPIO resources held by the compatibility controller."""
    _controller.cleanup()
