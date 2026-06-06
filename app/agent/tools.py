from __future__ import annotations

import sqlite3
from typing import Any

from app.nutrition.calculator import NutritionCalculator
from app.usda.lookup import IngredientLookup


def build_agent_tools(connection: sqlite3.Connection):
    lookup = IngredientLookup(connection)
    calculator = NutritionCalculator(connection)

    def get_ingredient_nutrition(
        ingredient_name: str,
        preferred_food_category: str | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Get USDA nutrition data and portion conversions for one standard English ingredient."""
        return lookup.get_ingredient_nutrition(ingredient_name, preferred_food_category, max_results)

    def calculate_total_nutrition(
        ingredients: list[dict[str, Any]],
        servings: float | None = None,
    ) -> dict[str, Any]:
        """Calculate per-ingredient, total, and optional per-serving nutrition for a recipe."""
        return calculator.calculate_total_nutrition(ingredients, servings)

    return [get_ingredient_nutrition, calculate_total_nutrition]
