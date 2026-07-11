"""BarRobot application factory."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from flask import Flask

from .config import ConfigStore
from .hardware import HardwareController
from .recipes import CocktailDbClient, RecipeRepository
from .routes import web


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create and configure the BarRobot Flask application.

    Args:
        test_config: Optional Flask and BarRobot service overrides used by tests.

    Returns:
        A configured Flask application.
    """
    project_dir = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder=str(project_dir / "templates"),
        static_folder=str(project_dir / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.getenv("BARROBOT_SECRET_KEY") or secrets.token_hex(32),
        CONFIG_PATH=project_dir / "config.json",
        LEGACY_CONFIG_PATH=project_dir / "bottle_config.json",
        RECIPES_PATH=project_dir / "recipes.json",
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)

    config_store = app.config.get("BARROBOT_CONFIG_STORE") or ConfigStore(
        Path(app.config["CONFIG_PATH"]),
        Path(app.config["LEGACY_CONFIG_PATH"]),
    )
    recipe_repository = app.config.get("BARROBOT_RECIPE_REPOSITORY") or RecipeRepository(
        Path(app.config["RECIPES_PATH"]),
        CocktailDbClient(),
    )

    config = config_store.load()
    hardware = app.config.get("BARROBOT_HARDWARE") or HardwareController(
        pin_map=config.pins,
        safe_mode=config.safe_mode,
    )

    app.extensions["barrobot.config_store"] = config_store
    app.extensions["barrobot.recipe_repository"] = recipe_repository
    app.extensions["barrobot.hardware"] = hardware
    app.register_blueprint(web)
    return app


__all__ = ["create_app"]
