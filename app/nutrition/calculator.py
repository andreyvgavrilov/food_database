from __future__ import annotations

import sqlite3
from typing import Any

from app.usda.lookup import IngredientLookup
from app.usda.units import convert_to_grams


class NutritionCalculator:
    def __init__(self, connection: sqlite3.Connection):
        self.lookup = IngredientLookup(connection)

    def calculate_total_nutrition(self, ingredients: list[dict[str, Any]], servings: float | None = None) -> dict[str, Any]:
        ingredient_rows: list[dict[str, Any]] = []
        totals: dict[str, dict[str, float | str | None]] = {}
        total_weight_grams = 0.0
        warnings: list[str] = []

        for ingredient in ingredients:
            name = _ingredient_name(ingredient)
            quantity, unit = _ingredient_quantity_and_unit(ingredient)
            if not name:
                warning = "Ingredient name is missing."
                warnings.append(warning)
                ingredient_rows.append(
                    {
                        "input_name": "",
                        "resolved_name": None,
                        "fdc_id": None,
                        "quantity": quantity,
                        "unit": unit,
                        "grams": None,
                        "nutrition": {},
                        "warnings": [warning],
                    }
                )
                continue

            lookup_result = self.lookup.get_ingredient_nutrition(name, max_results=1)

            if not lookup_result["matches"]:
                warning = f"No USDA match found for '{name}'."
                warnings.append(warning)
                ingredient_rows.append(
                    {
                        "input_name": name,
                        "resolved_name": None,
                        "fdc_id": None,
                        "quantity": quantity,
                        "unit": unit,
                        "grams": None,
                        "nutrition": {},
                        "warnings": [warning],
                    }
                )
                continue

            match = lookup_result["matches"][0]
            conversion = convert_to_grams(quantity, unit, match["portion_conversions"])
            row_warnings = []
            if conversion.warning:
                row_warnings.append(conversion.warning)
                warnings.append(f"{name}: {conversion.warning}")

            nutrition: dict[str, dict[str, float | str | None]] = {}
            if conversion.grams is not None:
                total_weight_grams = round(total_weight_grams + conversion.grams, 4)
                for nutrient_name, nutrient in match["nutrients_per_100g"].items():
                    amount = nutrient.get("amount")
                    if amount is None:
                        continue
                    scaled_amount = round(float(amount) * conversion.grams / 100, 4)
                    nutrition[nutrient_name] = {
                        "amount": scaled_amount,
                        "unit": nutrient.get("unit"),
                    }
                    total = totals.setdefault(
                        nutrient_name,
                        {"amount": 0.0, "unit": nutrient.get("unit")},
                    )
                    total["amount"] = round(float(total["amount"] or 0) + scaled_amount, 4)

            ingredient_rows.append(
                {
                    "input_name": name,
                    "resolved_name": match["description"],
                    "fdc_id": match["fdc_id"],
                    "quantity": quantity,
                    "unit": unit,
                    "grams": round(conversion.grams, 4) if conversion.grams is not None else None,
                    "nutrition": nutrition,
                    "warnings": row_warnings,
                }
            )

        per_serving = None
        if servings and servings > 0:
            per_serving = {
                name: {
                    "amount": round(float(nutrient["amount"] or 0) / servings, 4),
                    "unit": nutrient.get("unit"),
                }
                for name, nutrient in totals.items()
            }

        per_100g = None
        if total_weight_grams > 0:
            per_100g = {
                name: {
                    "amount": round(float(nutrient["amount"] or 0) / total_weight_grams * 100, 4),
                    "unit": nutrient.get("unit"),
                }
                for name, nutrient in totals.items()
            }

        return {
            "ingredients": ingredient_rows,
            "total_weight_grams": total_weight_grams,
            "total": totals,
            "per_100g": per_100g,
            "per_serving": per_serving,
            "warnings": warnings,
        }


def _ingredient_name(ingredient: dict[str, Any]) -> str:
    for key in (
        "name",
        "ingredient_name",
        "input_name",
        "standard_english_name",
        "standard_name",
        "original_name",
        "description",
    ):
        value = ingredient.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _ingredient_quantity_and_unit(ingredient: dict[str, Any]) -> tuple[float, str]:
    for grams_key in ("grams", "weight_grams", "weight_g"):
        grams = _float_or_none(ingredient.get(grams_key))
        if grams is not None:
            return grams, "gram"

    quantity = _float_or_none(ingredient.get("quantity"))
    if quantity is None:
        quantity = _float_or_none(ingredient.get("amount"))
    if quantity is None:
        quantity = _float_or_none(ingredient.get("weight"))
    if quantity is None:
        quantity = 0.0

    unit = ingredient.get("unit") or ingredient.get("measure") or ingredient.get("unit_name") or "gram"
    return quantity, str(unit).strip() or "gram"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
