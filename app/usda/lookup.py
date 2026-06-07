from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

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

GENERIC_SINGLE_FOOD_DESCRIPTORS = {
    "all",
    "boiled",
    "cooked",
    "dry",
    "dried",
    "fresh",
    "frozen",
    "large",
    "plain",
    "raw",
    "regular",
    "ripe",
    "small",
    "unspecified",
    "whole",
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
    ) -> list[Mapping[str, Any]]:
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
        term_variants = [sorted(_term_variants(term)) for term in terms]
        token_match_clauses = [
            "(" + " OR ".join(["(' ' || foods.search_name || ' ') LIKE ?"] * len(variants)) + ")"
            for variants in term_variants
        ]
        token_match_where = " AND ".join(token_match_clauses)

        category_join = ""
        if preferred_food_category:
            category_join = "LEFT JOIN food_categories ON food_categories.id = foods.food_category_id"

        if token_match_where:
            where = f"({token_match_where})"
        else:
            where = "1 = 0"

        query_params: list[object] = []
        for variants in term_variants:
            query_params.extend([f"% {variant} %" for variant in variants])
        query_params.append(max(max_results * 20, max_results))

        rows = self.connection.execute(
            f"""
            SELECT
              foods.fdc_id,
              foods.description,
              foods.search_name
              {", food_categories.description AS category_description" if preferred_food_category else ""}
            FROM foods
            {category_join}
            WHERE {where}
            ORDER BY LENGTH(foods.description), foods.description
            LIMIT ?
            """,
            query_params,
        ).fetchall()
        ranked_rows = []
        for row in rows:
            confidence = _search_confidence(normalized, terms, str(row["search_name"] or ""))
            if confidence is None:
                continue
            if preferred_food_category:
                category_description = str(row["category_description"] or "")
                if preferred_food_category.lower() in category_description.lower():
                    confidence += 0.05
            ranked_rows.append(
                {
                    "fdc_id": row["fdc_id"],
                    "description": row["description"],
                    "search_name": row["search_name"],
                    "confidence": confidence,
                }
            )

        ranked_rows.sort(key=lambda row: (-float(row["confidence"]), len(str(row["description"])), str(row["description"])))
        return ranked_rows[:max_results]

    def _hydrate_match(self, row: Mapping[str, Any]) -> NutritionMatch:
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


def _search_confidence(normalized_query: str, terms: list[str], search_name: str) -> float | None:
    if not terms:
        return None
    search_tokens = search_name.split()
    query_tokens = normalized_query.split()
    if search_name == normalized_query:
        return 1.0
    if _contains_token_phrase(search_tokens, query_tokens):
        confidence = 0.95
        if len(query_tokens) == 1:
            confidence += _single_ingredient_match_adjustment(query_tokens[0], search_tokens)
        return max(0.0, min(confidence, 0.99))
    if all(_term_matches_token(term, search_tokens) for term in terms):
        return 0.86
    return None


def _single_ingredient_match_adjustment(query_token: str, search_tokens: list[str]) -> float:
    if not search_tokens:
        return 0.0
    if search_tokens[0] != query_token:
        return -0.07
    if any(token in GENERIC_SINGLE_FOOD_DESCRIPTORS for token in search_tokens[1:]):
        return 0.04
    return 0.01


def _contains_token_phrase(tokens: list[str], query_tokens: list[str]) -> bool:
    if not query_tokens or len(query_tokens) > len(tokens):
        return False
    phrase_length = len(query_tokens)
    return any(tokens[index : index + phrase_length] == query_tokens for index in range(len(tokens) - phrase_length + 1))


def _term_matches_token(term: str, tokens: list[str]) -> bool:
    variants = _term_variants(term)
    return any(token in variants or (len(term) >= 4 and any(token.startswith(variant) for variant in variants)) for token in tokens)


def _term_variants(term: str) -> set[str]:
    variants = {term}
    if term.endswith("ies") and len(term) > 3:
        variants.add(term[:-3] + "y")
    if term.endswith("y") and len(term) > 3:
        variants.add(term[:-1] + "ies")
    if term.endswith("s") and len(term) > 3:
        variants.add(term[:-1])
    else:
        variants.add(term + "s")
    return variants
