from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.usda.normalize import normalize_search_text


DIRECT_GRAM_UNITS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "mg": 0.001,
    "milligram": 0.001,
    "milligrams": 0.001,
}

UNIT_ALIASES = {
    "tbsp": "tablespoon",
    "tbs": "tablespoon",
    "tablespoons": "tablespoon",
    "teaspoons": "teaspoon",
    "tsp": "teaspoon",
    "cups": "cup",
    "pieces": "piece",
    "slice": "slice",
    "slices": "slice",
    "servings": "serving",
}


@dataclass(frozen=True)
class GramConversion:
    grams: float | None
    warning: str | None = None


def normalize_unit(unit: str) -> str:
    normalized = normalize_search_text(unit)
    return UNIT_ALIASES.get(normalized, normalized)


def convert_to_grams(quantity: float, unit: str, portions: list[dict[str, Any]]) -> GramConversion:
    normalized_unit = normalize_unit(unit)
    if normalized_unit in DIRECT_GRAM_UNITS:
        return GramConversion(quantity * DIRECT_GRAM_UNITS[normalized_unit])

    for portion in portions:
        portion_unit = normalize_unit(str(portion.get("unit") or ""))
        modifier = normalize_unit(str(portion.get("modifier") or ""))
        amount = portion.get("amount") or 1
        gram_weight = portion.get("gram_weight")
        if gram_weight is None:
            continue
        if normalized_unit not in {portion_unit, modifier}:
            continue
        try:
            portion_amount = float(amount) if float(amount) else 1.0
            return GramConversion(quantity * float(gram_weight) / portion_amount)
        except (TypeError, ValueError):
            continue

    return GramConversion(
        None,
        f"No gram conversion found for unit '{unit}'. Provide grams or use a USDA-supported portion.",
    )
