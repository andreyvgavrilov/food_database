from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from app.usda.normalize import normalize_search_text


PRIORITY_NUTRIENTS = {
    "Energy",
    "Protein",
    "Total lipid (fat)",
    "Fatty acids, total saturated",
    "Carbohydrate, by difference",
    "Sugars, total including NLEA",
    "Total Sugars",
    "Fiber, total dietary",
    "Sodium, Na",
    "Cholesterol",
    "Potassium, K",
    "Calcium, Ca",
    "Iron, Fe",
}


@dataclass(frozen=True)
class NutritionMatch:
    fdc_id: int
    description: str
    confidence: float
    nutrients_per_100g: dict[str, dict[str, float | str | None]]
    portion_conversions: list[dict[str, float | str | None]]


class IngredientLookup:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get_ingredient_nutrition(
        self,
        ingredient_name: str,
        preferred_food_category: str | None = None,
        max_results: int = 5,
    ) -> dict[str, Any]:
        normalized = normalize_search_text(ingredient_name)
        candidates = self._candidate_rows(ingredient_name, normalized, preferred_food_category, max_results)
        matches = [self._hydrate_match(row) for row in candidates]
        return {
            "ingredient_name": ingredient_name,
            "matches": [
                {
                    "fdc_id": match.fdc_id,
                    "description": match.description,
                    "confidence": match.confidence,
                    "nutrients_per_100g": match.nutrients_per_100g,
                    "portion_conversions": match.portion_conversions,
                }
                for match in matches
            ],
        }

    def _candidate_rows(
        self,
        ingredient_name: str,
        normalized: str,
        preferred_food_category: str | None,
        max_results: int,
    ) -> list[sqlite3.Row]:
        alias_row = self.connection.execute(
            """
            SELECT foods.fdc_id, foods.description, foods.search_name, ingredient_aliases.confidence
            FROM ingredient_aliases
            JOIN foods ON foods.fdc_id = ingredient_aliases.fdc_id
            WHERE ingredient_aliases.original_name = ?
               OR ingredient_aliases.normalized_name = ?
            ORDER BY ingredient_aliases.confidence DESC
            LIMIT 1
            """,
            (ingredient_name, normalized),
        ).fetchone()
        if alias_row:
            return [alias_row]

        terms = [term for term in normalized.split() if term]
        like_all_terms = " AND ".join(["foods.search_name LIKE ?"] * len(terms))
        params: list[object] = [f"%{term}%" for term in terms]

        category_join = ""
        category_score = "0"
        if preferred_food_category:
            category_join = "LEFT JOIN food_categories ON food_categories.id = foods.food_category_id"
            category_score = "CASE WHEN food_categories.description LIKE ? THEN 0.05 ELSE 0 END"
            params.insert(0, f"%{preferred_food_category}%")

        if like_all_terms:
            where = f"({like_all_terms})"
        else:
            where = "1 = 0"

        query_params: list[object] = []
        if preferred_food_category:
            query_params.append(f"%{preferred_food_category}%")
        query_params.extend([normalized, f"%{normalized}%"])
        query_params.extend([f"%{term}%" for term in terms])
        query_params.append(max_results)

        rows = self.connection.execute(
            f"""
            SELECT
              foods.fdc_id,
              foods.description,
              foods.search_name,
              CASE
                WHEN foods.search_name = ? THEN 1.0
                WHEN foods.search_name LIKE ? THEN 0.9
                ELSE 0.72
              END + {category_score} AS confidence
            FROM foods
            {category_join}
            WHERE {where}
            ORDER BY confidence DESC, LENGTH(foods.description), foods.description
            LIMIT ?
            """,
            query_params,
        ).fetchall()
        return rows

    def _hydrate_match(self, row: sqlite3.Row) -> NutritionMatch:
        nutrient_rows = self.connection.execute(
            """
            SELECT nutrients.name, nutrients.unit_name, food_nutrients.amount
            FROM food_nutrients
            JOIN nutrients ON nutrients.id = food_nutrients.nutrient_id
            WHERE food_nutrients.fdc_id = ?
            ORDER BY nutrients.name
            """,
            (row["fdc_id"],),
        ).fetchall()
        nutrients = {
            nutrient["name"]: {
                "amount": nutrient["amount"],
                "unit": nutrient["unit_name"],
            }
            for nutrient in nutrient_rows
            if nutrient["name"] in PRIORITY_NUTRIENTS
        }

        portion_rows = self.connection.execute(
            """
            SELECT amount, measure_unit_name, modifier, gram_weight
            FROM food_portions
            WHERE fdc_id = ?
            ORDER BY measure_unit_name, modifier
            """,
            (row["fdc_id"],),
        ).fetchall()
        portions = [
            {
                "amount": portion["amount"],
                "unit": portion["measure_unit_name"],
                "modifier": portion["modifier"],
                "gram_weight": portion["gram_weight"],
            }
            for portion in portion_rows
        ]

        return NutritionMatch(
            fdc_id=int(row["fdc_id"]),
            description=str(row["description"]),
            confidence=float(row["confidence"]),
            nutrients_per_100g=nutrients,
            portion_conversions=portions,
        )
