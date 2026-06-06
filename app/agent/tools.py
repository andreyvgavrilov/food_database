from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db import connect
from app.nutrition.calculator import NutritionCalculator
from app.usda.lookup import IngredientLookup


def build_agent_tools(database_path: Path):
    def get_ingredient_nutrition(
        ingredient_name: str,
        preferred_food_category: str | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Get USDA nutrition data and portion conversions for one standard English ingredient."""
        connection = connect(database_path)
        try:
            return IngredientLookup(connection).get_ingredient_nutrition(
                ingredient_name,
                preferred_food_category,
                max_results,
            )
        finally:
            connection.close()

    def calculate_total_nutrition(
        ingredients: list[dict[str, Any]],
        servings: float | None = None,
    ) -> dict[str, Any]:
        """Calculate per-ingredient, total, and optional per-serving nutrition for a recipe."""
        connection = connect(database_path)
        try:
            return NutritionCalculator(connection).calculate_total_nutrition(ingredients, servings)
        finally:
            connection.close()

    return [get_ingredient_nutrition, calculate_total_nutrition]
