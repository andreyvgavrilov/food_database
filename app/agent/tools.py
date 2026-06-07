from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.interaction_logs import InteractionLogger
from app.agent.ollama import IngredientNormalizer
from app.config import Settings
from app.db import connect
from app.nutrition.calculator import NutritionCalculator
from app.usda.lookup import IngredientLookup
from app.usda.normalize import normalize_search_text


def build_agent_tools(settings_or_database_path: Settings | Path):
    settings = settings_or_database_path if isinstance(settings_or_database_path, Settings) else None
    database_path = settings.database_path if settings else settings_or_database_path
    logger = InteractionLogger(settings.interaction_logs_path) if settings else None

    def get_ingredient_nutrition(
        ingredient_name: str,
        preferred_food_category: str | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Get USDA nutrition data and portion conversions for one standard English ingredient."""
        input_payload = {
            "ingredient_name": ingredient_name,
            "preferred_food_category": preferred_food_category,
            "max_results": max_results,
        }
        normalized_ingredient_name = ingredient_name
        normalization_warning = None
        try:
            if settings:
                try:
                    normalized = IngredientNormalizer(settings).normalize(
                        [{"name": ingredient_name, "quantity": 100, "unit": "gram"}]
                    )
                    if normalized and normalized[0].get("name"):
                        candidate_name = str(normalized[0]["name"])
                        normalized_ingredient_name = _safe_normalized_name(ingredient_name, candidate_name)
                        if normalized_ingredient_name != candidate_name:
                            normalization_warning = (
                                f"Ingredient normalization returned broader name '{candidate_name}', "
                                f"using submitted name '{ingredient_name}'."
                            )
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
                _log_tool(logger, "get_ingredient_nutrition", input_payload, result)
                return result
            finally:
                connection.close()
        except Exception as exc:
            _log_tool(logger, "get_ingredient_nutrition", input_payload, error=str(exc))
            raise

    def calculate_total_nutrition(
        ingredients: list[dict[str, Any]],
        servings: float | None = None,
    ) -> dict[str, Any]:
        """Calculate per-ingredient, total, per-100g, and optional per-serving nutrition for a recipe.

        Pass the original user ingredient names and quantities. This tool normalizes non-English,
        transliterated, and regional ingredient names internally before USDA lookup.
        """
        input_payload = {"ingredients": ingredients, "servings": servings}
        normalization_warning = None
        try:
            if settings:
                try:
                    normalized_ingredients = IngredientNormalizer(settings).normalize(ingredients)
                    ingredients, broadening_warnings = _safe_normalized_ingredients(ingredients, normalized_ingredients)
                    if broadening_warnings:
                        normalization_warning = " ".join(broadening_warnings)
                except Exception as exc:
                    normalization_warning = f"Ingredient normalization unavailable, using submitted names: {exc}"

            connection = connect(database_path)
            try:
                result = NutritionCalculator(connection).calculate_total_nutrition(ingredients, servings)
                if normalization_warning:
                    result["warnings"].insert(0, normalization_warning)
                _log_tool(logger, "calculate_total_nutrition", input_payload, result)
                return result
            finally:
                connection.close()
        except Exception as exc:
            _log_tool(logger, "calculate_total_nutrition", input_payload, error=str(exc))
            raise

    return [get_ingredient_nutrition, calculate_total_nutrition]


def _log_tool(
    logger: InteractionLogger | None,
    name: str,
    input_payload: dict[str, Any],
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if not logger:
        return
    payload: dict[str, Any] = {"input": input_payload}
    if output is not None:
        payload["output"] = output
    if error is not None:
        payload["error"] = error
    logger.write("tool", name, payload)


def _safe_normalized_ingredients(
    original_ingredients: list[dict[str, Any]],
    normalized_ingredients: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    safe_ingredients: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, normalized_ingredient in enumerate(normalized_ingredients):
        original_ingredient = original_ingredients[index] if index < len(original_ingredients) else {}
        original_name = _ingredient_name(original_ingredient)
        candidate_name = _ingredient_name(normalized_ingredient)
        if original_name and candidate_name:
            safe_name = _safe_normalized_name(original_name, candidate_name)
            if safe_name != candidate_name:
                normalized_ingredient = {**normalized_ingredient, "name": safe_name, "original_name": original_name}
                warnings.append(
                    f"Ingredient normalization returned broader name '{candidate_name}', "
                    f"using submitted name '{original_name}'."
                )
        safe_ingredients.append(normalized_ingredient)
    return safe_ingredients, warnings


def _safe_normalized_name(original_name: str, candidate_name: str) -> str:
    original_terms = set(normalize_search_text(original_name).split())
    candidate_terms = set(normalize_search_text(candidate_name).split())
    if not original_terms or not candidate_terms:
        return candidate_name
    if original_terms < candidate_terms:
        return original_name
    return candidate_name


def _ingredient_name(ingredient: dict[str, Any]) -> str:
    for key in ("name", "ingredient_name", "input_name", "standard_english_name", "original_name", "description"):
        value = ingredient.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
