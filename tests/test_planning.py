"""Availability and preflight planning tests."""

from __future__ import annotations

import pytest

from barrobot.config import BarRobotConfig
from barrobot.planning import ActionKind, MissingIngredientsError, build_plan, makeable
from barrobot.recipes import Ingredient, Recipe


def test_plan_resolves_slot_pantry_substitution_and_shot_size() -> None:
    """Planning resolves inventory and makes shot size control repetitions."""
    config = BarRobotConfig.from_mapping(
        {
            "shot_size": 0.75,
            "slots": ["dark rum", "cola"],
            "pantry": ["lime"],
            "substitutions": {"white rum": "dark rum"},
        }
    )
    recipe = Recipe(
        "1",
        "Test",
        "",
        "",
        (
            Ingredient("white rum", 1.5),
            Ingredient("cola", 3.0),
            Ingredient("lime", 0.0),
        ),
    )

    plan = build_plan(recipe, config)

    assert [action.kind for action in plan.actions] == [
        ActionKind.AUTOMATIC,
        ActionKind.AUTOMATIC,
        ActionKind.MANUAL,
    ]
    assert plan.actions[0].slot == 0
    assert plan.actions[0].repetitions == 2
    assert plan.actions[1].repetitions == 4


def test_plan_rejects_all_missing_items_before_actions() -> None:
    """No partial plan is returned when any later ingredient is missing."""
    recipe = Recipe(
        "1",
        "Test",
        "",
        "",
        (
            Ingredient("rum", 1.5),
            Ingredient("cola", 3.0),
            Ingredient("lime", 0.0),
        ),
    )
    config = BarRobotConfig.from_mapping({"slots": ["rum"]})

    with pytest.raises(MissingIngredientsError) as error:
        build_plan(recipe, config)

    assert error.value.missing == ("cola", "lime")
    assert not makeable(recipe, config)
