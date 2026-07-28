"""Shared test doubles and fixtures."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pytest

from barrobot.config import BarRobotConfig, ConfigStore
from barrobot.hardware import HardwareController
from barrobot.recipes import Ingredient, Recipe


@dataclass
class RecordingGpio:
    """In-memory GPIO adapter that records setup, output, and cleanup."""

    setups: list[tuple[int, ...]] = field(default_factory=list)
    outputs: list[tuple[int, bool]] = field(default_factory=list)
    cleanup_count: int = 0

    def setup_outputs(self, pins: Iterable[int]) -> None:
        """Record configured output pins."""
        self.setups.append(tuple(pins))

    def output(self, pin: int, high: bool) -> None:
        """Record one pin state transition."""
        self.outputs.append((pin, high))

    def cleanup(self) -> None:
        """Record one cleanup call."""
        self.cleanup_count += 1


class StaticRecipeRepository:
    """Recipe repository test double returning a fixed catalogue."""

    def __init__(self, recipes: tuple[Recipe, ...]) -> None:
        self.recipes = recipes
        self.api_keys: list[str] = []

    def load(self, api_key: str = "1") -> tuple[Recipe, ...]:
        """Return fixed recipes and record the requested API key."""
        self.api_keys.append(api_key)
        return self.recipes


@pytest.fixture
def recipes() -> tuple[Recipe, ...]:
    """Return a small catalogue containing makeable and missing recipes."""
    return (
        Recipe(
            id="1",
            name="Rum and Cola",
            image="https://example.test/rum.jpg",
            instructions="Combine.",
            ingredients=(
                Ingredient("rum", 1.5, "1 1/2 oz"),
                Ingredient("cola", 3.0, "3 oz"),
            ),
        ),
        Recipe(
            id="2",
            name="Gin and Tonic",
            image="",
            instructions="Combine.",
            ingredients=(
                Ingredient("gin", 1.5, "1 1/2 oz"),
                Ingredient("tonic water", 3.0, "3 oz"),
            ),
        ),
    )


@pytest.fixture
def app(tmp_path: Any, recipes: tuple[Recipe, ...]):
    """Create an isolated safe-mode Flask application."""
    from barrobot import create_app

    store = ConfigStore(tmp_path / "config.json", tmp_path / "legacy.json")
    store.save(
        BarRobotConfig.from_mapping(
            {
                "slots": ["rum", "gin"] + [None] * 10,
                "pantry": ["cola"],
                "safe_mode": True,
            }
        )
    )
    repository = StaticRecipeRepository(recipes)
    gpio = RecordingGpio()
    hardware = HardwareController(safe_mode=True, gpio=gpio, sleeper=lambda _: None)
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "CONFIG_PATH": tmp_path / "config.json",
            "LEGACY_CONFIG_PATH": tmp_path / "legacy.json",
            "RECIPES_PATH": tmp_path / "recipes.json",
            "BARROBOT_CONFIG_STORE": store,
            "BARROBOT_RECIPE_REPOSITORY": repository,
            "BARROBOT_HARDWARE": hardware,
        }
    )
    application.testing_services = {  # type: ignore[attr-defined]
        "store": store,
        "repository": repository,
        "gpio": gpio,
        "hardware": hardware,
    }
    return application


@pytest.fixture
def client(app: Any):
    """Return the isolated Flask test client."""
    return app.test_client()
