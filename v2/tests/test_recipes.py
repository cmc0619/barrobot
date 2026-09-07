"""Recipe conversion, downloading, and caching tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from barrobot.recipes import (
    CocktailDbClient,
    Ingredient,
    Recipe,
    RecipeRepository,
    quantity_to_ounces,
    scale_ingredients,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2 1/2 oz", 2.5),
        ("1/2 ounce", 0.5),
        ("30 ml", 1.01),
        ("3 cl", 1.01),
        ("1 lime wedge", 0.0),
        ("to taste", 0.0),
        (None, 0.0),
    ],
)
def test_quantity_to_ounces(raw: str | None, expected: float) -> None:
    """Common CocktailDB quantities retain v1-compatible conversion."""
    assert quantity_to_ounces(raw) == expected


def test_scale_ingredients_preserves_ratio_and_garnish() -> None:
    """The smallest liquid becomes 1.5 ounces while zero quantities remain zero."""
    scaled = scale_ingredients(
        (
            Ingredient("rum", 2.0),
            Ingredient("cola", 4.0),
            Ingredient("lime", 0.0),
        )
    )

    assert [item.qty_oz for item in scaled] == [1.5, 3.0, 0.0]


@dataclass
class FakeResponse:
    """Minimal successful HTTP response."""

    payload: dict[str, Any]

    def raise_for_status(self) -> None:
        """Represent a successful status."""

    def json(self) -> dict[str, Any]:
        """Return the configured JSON body."""
        return self.payload


class FakeHttp:
    """HTTP client that records CocktailDB requests."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """Record a request and return a fixed response."""
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def test_paid_download_uses_single_call_and_converts_recipe() -> None:
    """A paid key uses the catalogue endpoint once and returns normalized data."""
    http = FakeHttp(
        {
            "drinks": [
                {
                    "idDrink": "99",
                    "strDrink": " Test Drink ",
                    "strDrinkThumb": "image",
                    "strInstructions": "Stir",
                    "strIngredient1": " Gin ",
                    "strMeasure1": "1 oz",
                }
            ]
        }
    )

    recipes = CocktailDbClient(http).download("paid-key")

    assert len(http.calls) == 1
    assert "/v2/paid-key/search.php" in http.calls[0][0]
    assert recipes[0].name == "Test Drink"
    assert recipes[0].ingredients[0] == Ingredient("gin", 1.5, "1 oz")


def test_repository_uses_existing_compatible_cache_without_http(tmp_path) -> None:
    """An existing recipe cache avoids all network calls."""
    recipe = Recipe("1", "Cached", "", "", (Ingredient("rum", 1.5),))
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps([recipe.to_mapping()]))
    http = FakeHttp({"drinks": []})

    loaded = RecipeRepository(path, CocktailDbClient(http)).load()

    assert loaded == (recipe,)
    assert http.calls == []
