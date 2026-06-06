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
        warnings: list[str] = []

        for ingredient in ingredients:
            name = str(ingredient.get("name") or "").strip()
            quantity = float(ingredient.get("quantity") or 0)
            unit = str(ingredient.get("unit") or "gram").strip()
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

        return {
            "ingredients": ingredient_rows,
            "total": totals,
            "per_serving": per_serving,
            "warnings": warnings,
        }
