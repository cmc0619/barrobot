"""CocktailDB conversion, downloading, and local recipe caching."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

from .config import normalize_ingredient

FREE_BASE = "https://www.thecocktaildb.com/api/json/v1/1"


class RecipeError(RuntimeError):
    """Raised when recipes cannot be downloaded, parsed, or cached."""


@dataclass(frozen=True, slots=True)
class Ingredient:
    """One normalized recipe ingredient."""

    item: str
    qty_oz: float
    raw: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Ingredient:
        """Build an ingredient from the compatible recipe-cache schema."""
        item = normalize_ingredient(raw.get("item"))
        if not item:
            raise RecipeError("Recipe ingredient is missing its item name")
        try:
            quantity = float(raw.get("qty_oz", 0))
        except (TypeError, ValueError) as exc:
            raise RecipeError(f"Invalid quantity for ingredient {item}") from exc
        return cls(item=item, qty_oz=max(0.0, quantity), raw=str(raw.get("raw", "")))

    def to_mapping(self) -> dict[str, Any]:
        """Return the existing JSON cache representation."""
        return {"item": self.item, "qty_oz": self.qty_oz, "raw": self.raw}


@dataclass(frozen=True, slots=True)
class Recipe:
    """A normalized cocktail recipe."""

    id: str
    name: str
    image: str
    instructions: str
    ingredients: tuple[Ingredient, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Recipe:
        """Validate a cached or newly downloaded recipe mapping."""
        try:
            recipe_id = str(raw["id"])
            name = str(raw["name"]).strip()
            raw_ingredients = raw["ingredients"]
        except (KeyError, TypeError) as exc:
            raise RecipeError("Recipe is missing a required field") from exc
        if not name or not isinstance(raw_ingredients, list):
            raise RecipeError("Recipe name and ingredient list are required")
        return cls(
            id=recipe_id,
            name=name,
            image=str(raw.get("image") or ""),
            instructions=str(raw.get("instructions") or ""),
            ingredients=tuple(Ingredient.from_mapping(item) for item in raw_ingredients),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return the existing JSON cache representation."""
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "instructions": self.instructions,
            "ingredients": [ingredient.to_mapping() for ingredient in self.ingredients],
        }


_MIXED_FRACTION = re.compile(r"^(\d+)\s+(\d+)\s*/\s*(\d+)")
_SIMPLE_NUMBER = re.compile(r"^(\d+\s*/\s*\d+|\d+(?:\.\d+)?)")
_UNIT = re.compile(r"\b(oz|ounce|ounces|ml|cl)\b")
_NON_LIQUID_WORDS = ("slice", "wedge", "dash", "pinch", "sprig", "piece", "cube", "twist")


def quantity_to_ounces(raw: str | None) -> float:
    """Convert a CocktailDB measure to fluid ounces.

    Unquantified measures and obvious solid garnishes retain the legacy value
    of zero ounces.
    """
    if not raw:
        return 0.0
    text = raw.strip().lower()
    if any(word in text for word in _NON_LIQUID_WORDS):
        return 0.0

    mixed = _MIXED_FRACTION.match(text)
    if mixed:
        whole, numerator, denominator = (float(value) for value in mixed.groups())
        if denominator == 0:
            return 0.0
        quantity = whole + numerator / denominator
    else:
        simple = _SIMPLE_NUMBER.match(text)
        if not simple:
            return 0.0
        number = simple.group(1).replace(" ", "")
        if "/" in number:
            numerator, denominator = (float(value) for value in number.split("/", 1))
            if denominator == 0:
                return 0.0
            quantity = numerator / denominator
        else:
            quantity = float(number)

    unit_match = _UNIT.search(text)
    unit = unit_match.group(1) if unit_match else ""
    if unit == "ml":
        quantity *= 0.033814
    elif unit == "cl":
        quantity *= 0.33814
    return round(quantity, 2)


def scale_ingredients(ingredients: Iterable[Ingredient]) -> tuple[Ingredient, ...]:
    """Scale liquids so the smallest non-zero measure becomes 1.5 ounces."""
    items = tuple(ingredients)
    liquids = [ingredient.qty_oz for ingredient in items if ingredient.qty_oz > 0]
    if not liquids:
        return items
    factor = 1.5 / min(liquids)
    return tuple(
        Ingredient(
            item=ingredient.item,
            qty_oz=round(ingredient.qty_oz * factor, 2) if ingredient.qty_oz > 0 else 0.0,
            raw=ingredient.raw,
        )
        for ingredient in items
    )


class HttpResponse(Protocol):
    """Subset of a requests response used by the downloader."""

    def raise_for_status(self) -> None: ...
    def json(self) -> Mapping[str, Any]: ...


class HttpClient(Protocol):
    """Injectable HTTP client protocol used by tests."""

    def get(self, url: str, **kwargs: Any) -> HttpResponse: ...


class CocktailDbClient:
    """Download and normalize CocktailDB recipes."""

    def __init__(self, http: HttpClient | None = None) -> None:
        self.http = http or requests.Session()

    def download(self, api_key: str = "1") -> tuple[Recipe, ...]:
        """Download the full available catalogue for a free or paid API key."""
        drinks: list[Mapping[str, Any]] = []
        try:
            if api_key and api_key != "1":
                response = self.http.get(
                    f"https://www.thecocktaildb.com/api/json/v2/{api_key}/search.php",
                    params={"s": ""},
                    timeout=30,
                )
                response.raise_for_status()
                drinks.extend(response.json().get("drinks") or [])
            else:
                for letter in "abcdefghijklmnopqrstuvwxyz":
                    response = self.http.get(
                        f"{FREE_BASE}/search.php",
                        params={"f": letter},
                        timeout=10,
                    )
                    response.raise_for_status()
                    drinks.extend(response.json().get("drinks") or [])
        except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
            raise RecipeError(f"CocktailDB download failed: {exc}") from exc
        if not drinks:
            raise RecipeError("CocktailDB returned no recipes")
        return tuple(self._convert(drink) for drink in drinks)

    @staticmethod
    def _convert(raw: Mapping[str, Any]) -> Recipe:
        """Convert one CocktailDB object to the compatible cache model."""
        ingredients: list[Ingredient] = []
        for index in range(1, 16):
            item = normalize_ingredient(raw.get(f"strIngredient{index}"))
            if not item:
                continue
            measure = str(raw.get(f"strMeasure{index}") or "").strip()
            ingredients.append(Ingredient(item, quantity_to_ounces(measure), measure))
        try:
            recipe_id = str(raw["idDrink"])
            name = str(raw["strDrink"]).strip()
        except KeyError as exc:
            raise RecipeError("CocktailDB recipe is missing its id or name") from exc
        return Recipe(
            id=recipe_id,
            name=name,
            image=str(raw.get("strDrinkThumb") or ""),
            instructions=str(raw.get("strInstructions") or ""),
            ingredients=scale_ingredients(ingredients),
        )


class RecipeRepository:
    """Read compatible cached recipes or download them once when absent."""

    def __init__(self, path: Path, client: CocktailDbClient) -> None:
        self.path = path
        self.client = client

    def load(self, api_key: str = "1") -> tuple[Recipe, ...]:
        """Load cached recipes, downloading and caching only when absent."""
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RecipeError(f"Unable to read recipe cache {self.path}: {exc}") from exc
            if not isinstance(raw, list):
                raise RecipeError(f"Recipe cache {self.path} must contain a JSON list")
            return tuple(Recipe.from_mapping(recipe) for recipe in raw)

        recipes = self.client.download(api_key)
        self._save(recipes)
        return recipes

    def _save(self, recipes: Iterable[Recipe]) -> None:
        """Atomically save recipes in the existing JSON schema."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([recipe.to_mapping() for recipe in recipes], indent=2) + "\n"
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
            raise RecipeError(f"Unable to save recipe cache {self.path}: {exc}") from exc
