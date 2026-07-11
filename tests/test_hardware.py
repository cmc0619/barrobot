"""Hardware-controller tests using a recording GPIO adapter."""

from __future__ import annotations

import pytest
from conftest import RecordingGpio

from barrobot.hardware import HardwareController, PositionUnknownError


def test_safe_mode_tracks_position_without_gpio() -> None:
    """Dry-run rotation changes logical position and emits no GPIO output."""
    gpio = RecordingGpio()
    controller = HardwareController(safe_mode=True, gpio=gpio, sleeper=lambda _: None)

    controller.rotate_to_slot(7)
    controller.press_actuator(3)

    assert controller.current_slot == 7
    assert gpio.outputs == []
    assert gpio.setups == []


def test_live_rotation_requires_established_position() -> None:
    """A process restart cannot silently assume the physical turret is at zero."""
    controller = HardwareController(gpio=RecordingGpio(), sleeper=lambda _: None)

    with pytest.raises(PositionUnknownError, match="position is unknown"):
        controller.rotate_to_slot(1)


def test_safe_mode_position_is_not_trusted_when_live_mode_resumes() -> None:
    """A simulated move cannot define the physical starting position for live GPIO."""
    controller = HardwareController(safe_mode=True, gpio=RecordingGpio(), sleeper=lambda _: None)
    controller.rotate_to_slot(5)

    controller.set_safe_mode(False)

    assert controller.current_slot is None
    with pytest.raises(PositionUnknownError):
        controller.rotate_to_slot(6)


def test_full_revolution_distributes_exactly_1600_microsteps() -> None:
    """Twelve adjacent moves return to zero without truncated-step drift."""
    gpio = RecordingGpio()
    controller = HardwareController(gpio=gpio, sleeper=lambda _: None)
    controller.establish_position(0)

    for slot in range(1, 12):
        controller.rotate_to_slot(slot)
    controller.rotate_to_slot(0)

    step_highs = [event for event in gpio.outputs if event == (21, True)]
    assert len(step_highs) == 1600


def test_six_slot_tie_rotates_clockwise() -> None:
    """The existing clockwise tie-break remains part of the movement contract."""
    gpio = RecordingGpio()
    controller = HardwareController(gpio=gpio, sleeper=lambda _: None)
    controller.establish_position(0)

    controller.rotate_to_slot(6)

    assert (20, True) in gpio.outputs


def test_actuator_repetitions_and_cleanup_outputs() -> None:
    """Live dispensing pulses once per repetition and cleanup disables outputs."""
    gpio = RecordingGpio()
    controller = HardwareController(gpio=gpio, sleeper=lambda _: None)
    controller.establish_position(0)

    controller.press_actuator(2)
    controller.cleanup()

    assert gpio.outputs.count((26, True)) == 2
    assert gpio.cleanup_count == 1
    assert gpio.outputs[-2:] == [(26, False), (16, True)]


def test_failed_rotation_invalidates_position() -> None:
    """A partial physical move cannot leave the previous slot marked as trusted."""

    class FailingGpio(RecordingGpio):
        """GPIO adapter that fails on the first high step pulse."""

        def output(self, pin: int, high: bool) -> None:
            """Raise on movement after recording initial setup output."""
            super().output(pin, high)
            if pin == 21 and high:
                raise RuntimeError("simulated driver failure")

    gpio = FailingGpio()
    controller = HardwareController(gpio=gpio, sleeper=lambda _: None)
    controller.establish_position(0)

    with pytest.raises(Exception, match="Turret rotation failed"):
        controller.rotate_to_slot(1)

    assert controller.current_slot is None
    assert gpio.cleanup_count == 1
