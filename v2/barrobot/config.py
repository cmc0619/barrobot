"""Validated configuration models and atomic JSON persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOTAL_SLOTS = 12
DEFAULT_PIN_MAP = {"DIR": 20, "STEP": 21, "ENABLE": 16, "ACTUATOR": 26}
REQUIRED_PIN_SIGNALS = tuple(DEFAULT_PIN_MAP)


class ConfigError(RuntimeError):
    """Raised when configuration cannot be parsed or validated."""


def normalize_ingredient(value: Any) -> str | None:
    """Normalize a user or API ingredient value for case-insensitive matching."""
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().lower().split())
    return normalized or None


@dataclass(frozen=True, slots=True)
class BarRobotConfig:
    """Runtime configuration for recipes, bottles, and GPIO."""

    api_key: str = "1"
    shot_size: float = 1.5
    slots: tuple[str | None, ...] = (None,) * TOTAL_SLOTS
    pantry: tuple[str, ...] = ()
    substitutions: Mapping[str, str] = field(default_factory=dict)
    safe_mode: bool = False
    pins: Mapping[str, int] = field(default_factory=lambda: DEFAULT_PIN_MAP.copy())
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> BarRobotConfig:
        """Validate and normalize a mapping loaded from disk or a form."""
        data = dict(raw or {})
        api_key = str(data.pop("api_key", "1") or "1").strip()

        try:
            shot_size = float(data.pop("shot_size", 1.5))
        except (TypeError, ValueError) as exc:
            raise ConfigError("shot_size must be a number") from exc
        if shot_size < 0.5:
            raise ConfigError("shot_size must be at least 0.5 ounces")

        raw_slots = data.pop("slots", [None] * TOTAL_SLOTS)
        if not isinstance(raw_slots, (list, tuple)):
            raise ConfigError("slots must be a list")
        if len(raw_slots) > TOTAL_SLOTS:
            raise ConfigError(f"slots cannot contain more than {TOTAL_SLOTS} entries")
        slots = [normalize_ingredient(value) for value in raw_slots]
        slots.extend([None] * (TOTAL_SLOTS - len(slots)))

        raw_pantry = data.pop("pantry", [])
        if not isinstance(raw_pantry, (list, tuple)):
            raise ConfigError("pantry must be a list")
        pantry = tuple(
            dict.fromkeys(item for value in raw_pantry if (item := normalize_ingredient(value)))
        )

        raw_substitutions = data.pop("substitutions", {})
        if not isinstance(raw_substitutions, Mapping):
            raise ConfigError("substitutions must be an object")
        substitutions: dict[str, str] = {}
        for key, value in raw_substitutions.items():
            normalized_key = normalize_ingredient(key)
            normalized_value = normalize_ingredient(value)
            if normalized_key and normalized_value:
                substitutions[normalized_key] = normalized_value

        safe_mode = data.pop("safe_mode", False)
        if not isinstance(safe_mode, bool):
            raise ConfigError("safe_mode must be true or false")

        raw_pins = data.pop("pins", DEFAULT_PIN_MAP)
        if not isinstance(raw_pins, Mapping):
            raise ConfigError("pins must be an object")
        pins: dict[str, int] = {}
        for signal in REQUIRED_PIN_SIGNALS:
            try:
                pin = int(raw_pins.get(signal, DEFAULT_PIN_MAP[signal]))
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"{signal} pin must be an integer") from exc
            if not 0 <= pin <= 27:
                raise ConfigError(f"{signal} pin must be a BCM pin from 0 through 27")
            pins[signal] = pin
        if len(set(pins.values())) != len(pins):
            raise ConfigError("GPIO pins must be unique")

        return cls(
            api_key=api_key,
            shot_size=shot_size,
            slots=tuple(slots),
            pantry=pantry,
            substitutions=substitutions,
            safe_mode=safe_mode,
            pins=pins,
            extra=data,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping while retaining unknown keys."""
        return {
            **self.extra,
            "api_key": self.api_key,
            "shot_size": self.shot_size,
            "slots": list(self.slots),
            "pantry": list(self.pantry),
            "substitutions": dict(self.substitutions),
            "safe_mode": self.safe_mode,
            "pins": dict(self.pins),
        }


class ConfigStore:
    """Load and atomically persist the canonical BarRobot configuration."""

    def __init__(self, path: Path, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = legacy_path

    def load(self) -> BarRobotConfig:
        """Load configuration, importing the legacy file on first use."""
        source = self.path
        importing_legacy = not source.exists() and bool(
            self.legacy_path and self.legacy_path.exists()
        )
        if importing_legacy:
            source = self.legacy_path  # type: ignore[assignment]
        if not source.exists():
            return BarRobotConfig()

        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Unable to read configuration {source}: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise ConfigError(f"Configuration {source} must contain a JSON object")

        config = BarRobotConfig.from_mapping(raw)
        if importing_legacy:
            self.save(config)
        return config

    def save(self, config: BarRobotConfig) -> None:
        """Write configuration using an atomic replacement in the same directory."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_mapping(), indent=2) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.replace(self.path)
        except OSError as exc:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
            raise ConfigError(f"Unable to save configuration {self.path}: {exc}") from exc
