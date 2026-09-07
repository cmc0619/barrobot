"""Flask routes for the BarRobot touchscreen interface."""

from __future__ import annotations

import os
from typing import cast

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from .config import BarRobotConfig, ConfigError, ConfigStore, normalize_ingredient
from .hardware import HardwareController, HardwareError
from .planning import (
    ActionKind,
    MissingIngredientsError,
    build_plan,
    makeable,
    missing_ingredients,
)
from .recipes import Recipe, RecipeError, RecipeRepository

web = Blueprint("web", __name__)


def _config_store() -> ConfigStore:
    """Return the configured persistence service."""
    return cast(ConfigStore, current_app.extensions["barrobot.config_store"])


def _recipe_repository() -> RecipeRepository:
    """Return the configured recipe repository."""
    return cast(RecipeRepository, current_app.extensions["barrobot.recipe_repository"])


def _hardware() -> HardwareController:
    """Return the process-owned hardware controller."""
    return cast(HardwareController, current_app.extensions["barrobot.hardware"])


def _load_recipes(config: BarRobotConfig) -> tuple[Recipe, ...]:
    """Load recipes using the currently configured API key."""
    return _recipe_repository().load(os.getenv("COCKTAILDB_API_KEY") or config.api_key)


@web.get("/")
def menu():
    """Render recipes that can be completed with the current inventory."""
    try:
        config = _config_store().load()
        drinks = [recipe for recipe in _load_recipes(config) if makeable(recipe, config)]
        return render_template("menu.html", drinks=drinks)
    except (ConfigError, RecipeError) as exc:
        flash(str(exc), "error")
        return render_template("menu.html", drinks=[]), 503


@web.get("/drink/<drink_id>")
def drink_detail(drink_id: str):
    """Render one recipe by CocktailDB identifier."""
    try:
        config = _config_store().load()
        drink = next(
            (recipe for recipe in _load_recipes(config) if recipe.id == drink_id),
            None,
        )
    except (ConfigError, RecipeError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("web.menu"))
    if drink is None:
        flash("Drink not found", "error")
        return redirect(url_for("web.menu"))
    return render_template("drink.html", drink=drink)


@web.get("/suggestions")
def suggestions():
    """Render recipes missing exactly one ingredient."""
    try:
        config = _config_store().load()
        ideas = [
            {"recipe": recipe, "missing": missing[0]}
            for recipe in _load_recipes(config)
            if len(missing := missing_ingredients(recipe, config)) == 1
        ]
        return render_template("suggestions.html", ideas=ideas)
    except (ConfigError, RecipeError) as exc:
        flash(str(exc), "error")
        return render_template("suggestions.html", ideas=[]), 503


@web.get("/suggestions2")
def suggestions2():
    """Render recipes missing one or more ingredients."""
    try:
        config = _config_store().load()
        ideas = [
            {"recipe": recipe, "missing": missing}
            for recipe in _load_recipes(config)
            if (missing := missing_ingredients(recipe, config))
        ]
        return render_template("suggestions2.html", ideas=ideas)
    except (ConfigError, RecipeError) as exc:
        flash(str(exc), "error")
        return render_template("suggestions2.html", ideas=[]), 503


@web.route("/configure", methods=["GET", "POST"])
def configure():
    """Render or update bottle, pantry, substitution, and pour settings."""
    store = _config_store()
    try:
        config = store.load()
    except ConfigError as exc:
        flash(str(exc), "error")
        return render_template("configure.html", bottle_config=BarRobotConfig()), 503

    if request.method == "POST":
        try:
            updated = _config_from_form(config)
            store.save(updated)
            _hardware().set_pin_map(updated.pins)
            _hardware().set_safe_mode(updated.safe_mode)
        except (ConfigError, ValueError) as exc:
            flash(str(exc), "error")
            return render_template("configure.html", bottle_config=config), 400
        flash("Configuration saved.", "success")
        return redirect(url_for("web.menu"))
    return render_template("configure.html", bottle_config=config)


def _config_from_form(current: BarRobotConfig) -> BarRobotConfig:
    """Convert the configuration form to a fully validated model."""
    substitutions: dict[str, str] = {}
    for index in range(6):
        key = normalize_ingredient(request.form.get(f"sub_key{index}"))
        value = normalize_ingredient(request.form.get(f"sub_val{index}"))
        if key and value:
            substitutions[key] = value
    pantry = [
        item
        for value in (request.form.get("pantry") or "").split(",")
        if (item := normalize_ingredient(value))
    ]
    return BarRobotConfig.from_mapping(
        {
            **current.extra,
            "api_key": current.api_key,
            "shot_size": request.form.get("shot_size") or "1.5",
            "slots": [request.form.get(f"slot{index}") for index in range(12)],
            "pantry": pantry,
            "substitutions": substitutions,
            "safe_mode": request.form.get("safe_mode") == "on",
            "pins": current.pins,
        }
    )


@web.route("/motor", methods=["GET", "POST"])
def motor_controls():
    """Render or update the GPIO pin map and trusted turret position."""
    store = _config_store()
    try:
        config = store.load()
        if request.method == "POST":
            updated = BarRobotConfig.from_mapping(
                {
                    **config.to_mapping(),
                    "pins": {
                        signal: request.form.get(signal)
                        for signal in ("DIR", "STEP", "ENABLE", "ACTUATOR")
                    },
                }
            )
            store.save(updated)
            _hardware().set_pin_map(updated.pins)
            flash("Pin map saved.", "success")
            return redirect(url_for("web.motor_controls"))
        return render_template(
            "motor_controls.html",
            pins=config.pins,
            current_slot=_hardware().current_slot,
            safe_mode=config.safe_mode,
        )
    except (ConfigError, ValueError) as exc:
        flash(str(exc), "error")
        return (
            redirect(url_for("web.motor_controls"))
            if request.method == "POST"
            else (
                render_template(
                    "motor_controls.html",
                    pins=BarRobotConfig().pins,
                    current_slot=None,
                    safe_mode=False,
                ),
                400,
            )
        )


@web.post("/api/position/<int:slot>")
def api_position(slot: int):
    """Establish the current one-based slot without moving the turret."""
    if not 1 <= slot <= 12:
        return jsonify(status="error", msg="slot must be from 1 through 12"), 400
    _hardware().establish_position(slot - 1)
    return jsonify(status="ok", slot=slot)


@web.post("/api/rotate/<int:slot>")
def api_rotate(slot: int):
    """Rotate immediately to a one-based slot after validating runtime state."""
    if not 1 <= slot <= 12:
        return jsonify(status="error", msg="slot must be from 1 through 12"), 400
    try:
        config = _config_store().load()
        hardware = _hardware()
        hardware.set_pin_map(config.pins)
        hardware.set_safe_mode(config.safe_mode)
        hardware.rotate_to_slot(slot - 1)
    except ConfigError as exc:
        return jsonify(status="error", msg=str(exc)), 400
    except HardwareError as exc:
        return jsonify(status="error", msg=str(exc)), 409
    return jsonify(status="ok", slot=slot)


@web.route("/make_drink/<name>", methods=["GET", "POST"])
def make_drink(name: str):
    """Preflight and synchronously execute a complete drink plan.

    GET remains supported for v1 bookmarks, while the v2 menu submits POST.
    """
    try:
        config = _config_store().load()
        drink = next(
            (
                recipe
                for recipe in _load_recipes(config)
                if recipe.name.casefold() == name.casefold()
            ),
            None,
        )
        if drink is None:
            flash(f"No recipe named “{name}”.", "error")
            return redirect(url_for("web.menu"))
        plan = build_plan(drink, config)
        hardware = _hardware()
        hardware.set_pin_map(config.pins)
        hardware.set_safe_mode(config.safe_mode)

        with hardware.operation():
            for index, action in enumerate(plan.actions):
                verb = "Pulling" if index == 0 else "Adding"
                flash(f"{verb} {action.item}…", "info")
                if action.kind is ActionKind.AUTOMATIC:
                    hardware.rotate_to_slot(cast(int, action.slot))
                    flash(f"Dispensing {action.qty_oz:g} oz!", "info")
                    hardware.press_actuator(action.repetitions)
                else:
                    flash(
                        f"(Pantry) Please add {action.qty_oz:g} oz {action.item} manually.",
                        "info",
                    )
    except MissingIngredientsError as exc:
        flash(str(exc), "error")
        return redirect(url_for("web.menu"))
    except (ConfigError, RecipeError, HardwareError) as exc:
        _hardware().cleanup()
        flash(f"Drink stopped: {exc}", "error")
        return redirect(url_for("web.menu"))

    flash(f"{plan.recipe.name} is ready — cheers!", "success")
    return redirect(url_for("web.menu"))
