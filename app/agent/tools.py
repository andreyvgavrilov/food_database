from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.ollama import IngredientNormalizer
from app.config import Settings
from app.db import connect
from app.nutrition.calculator import NutritionCalculator
from app.usda.lookup import IngredientLookup


def build_agent_tools(settings_or_database_path: Settings | Path):
    settings = settings_or_database_path if isinstance(settings_or_database_path, Settings) else None
    database_path = settings.database_path if settings else settings_or_database_path

    def get_ingredient_nutrition(
        ingredient_name: str,
        preferred_food_category: str | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Get USDA nutrition data and portion conversions for one standard English ingredient."""
        normalized_ingredient_name = ingredient_name
        normalization_warning = None
        if settings:
            try:
                normalized = IngredientNormalizer(settings).normalize(
                    [{"name": ingredient_name, "quantity": 100, "unit": "gram"}]
                )
                if normalized and normalized[0].get("name"):
                    normalized_ingredient_name = str(normalized[0]["name"])
            except Exception as exc:
                normalization_warning = f"Ingredient normalization unavailable, using submitted name: {exc}"

        connection = connect(database_path)
        try:
            result = IngredientLookup(connection).get_ingredient_nutrition(
                normalized_ingredient_name,
                preferred_food_category,
                max_results,
            )
            if normalized_ingredient_name != ingredient_name:
                result["original_ingredient_name"] = ingredient_name
            if normalization_warning:
                result["warnings"] = [normalization_warning]
            return result
        finally:
            connection.close()

    def calculate_total_nutrition(
        ingredients: list[dict[str, Any]],
        servings: float | None = None,
    ) -> dict[str, Any]:
        """Calculate per-ingredient, total, per-100g, and optional per-serving nutrition for a recipe."""
        normalization_warning = None
        if settings:
            try:
                ingredients = IngredientNormalizer(settings).normalize(ingredients)
            except Exception as exc:
                normalization_warning = f"Ingredient normalization unavailable, using submitted names: {exc}"

        connection = connect(database_path)
        try:
            result = NutritionCalculator(connection).calculate_total_nutrition(ingredients, servings)
            if normalization_warning:
                result["warnings"].insert(0, normalization_warning)
            return result
        finally:
            connection.close()

    return [get_ingredient_nutrition, calculate_total_nutrition]
