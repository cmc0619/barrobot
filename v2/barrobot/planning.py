"""Pure recipe availability checks and drink pour planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import BarRobotConfig, normalize_ingredient
from .recipes import Ingredient, Recipe


class ActionKind(str, Enum):
    """Supported drink-plan action types."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class PourAction:
    """One preflighted automatic or manual ingredient action."""

    kind: ActionKind
    item: str
    qty_oz: float
    slot: int | None = None
    repetitions: int = 0


@dataclass(frozen=True, slots=True)
class DrinkPlan:
    """An immutable, ordered plan for one complete recipe."""

    recipe: Recipe
    actions: tuple[PourAction, ...]


class MissingIngredientsError(RuntimeError):
    """Raised before movement when a recipe cannot be completed."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"Missing ingredient(s): {', '.join(missing)}")


def resolved_item(item: str, config: BarRobotConfig) -> str | None:
    """Return the available exact or substituted ingredient name."""
    normalized = normalize_ingredient(item)
    if not normalized:
        return None
    if normalized in config.slots or normalized in config.pantry:
        return normalized
    substitute = config.substitutions.get(normalized)
    if substitute in config.slots or substitute in config.pantry:
        return substitute
    return None


def is_available(item: str, config: BarRobotConfig) -> bool:
    """Return whether an ingredient is available automatically or manually."""
    return resolved_item(item, config) is not None


def missing_ingredients(recipe: Recipe, config: BarRobotConfig) -> tuple[str, ...]:
    """Return unavailable ingredient names in recipe order without duplicates."""
    return tuple(
        dict.fromkeys(
            ingredient.item
            for ingredient in recipe.ingredients
            if not is_available(ingredient.item, config)
        )
    )


def makeable(recipe: Recipe, config: BarRobotConfig) -> bool:
    """Return whether every ingredient in a recipe is available."""
    return not missing_ingredients(recipe, config)


def build_plan(recipe: Recipe, config: BarRobotConfig) -> DrinkPlan:
    """Preflight a recipe and build all actions before hardware can move."""
    missing = missing_ingredients(recipe, config)
    if missing:
        raise MissingIngredientsError(missing)

    actions: list[PourAction] = []
    for ingredient in recipe.ingredients:
        actions.append(_action_for(ingredient, config))
    return DrinkPlan(recipe=recipe, actions=tuple(actions))


def _action_for(ingredient: Ingredient, config: BarRobotConfig) -> PourAction:
    """Resolve one known-available ingredient to a slot or pantry action."""
    available_item = resolved_item(ingredient.item, config)
    if available_item is None:
        raise MissingIngredientsError((ingredient.item,))
    if available_item in config.slots:
        repetitions = 0
        if ingredient.qty_oz > 0:
            repetitions = max(1, round(ingredient.qty_oz / config.shot_size))
        return PourAction(
            kind=ActionKind.AUTOMATIC,
            item=ingredient.item,
            qty_oz=ingredient.qty_oz,
            slot=config.slots.index(available_item),
            repetitions=repetitions,
        )
    return PourAction(
        kind=ActionKind.MANUAL,
        item=ingredient.item,
        qty_oz=ingredient.qty_oz,
    )
