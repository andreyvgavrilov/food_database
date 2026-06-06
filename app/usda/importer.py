from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.db import initialize_database, record_import_started, update_import_status
from app.usda.normalize import normalize_search_text


SOURCE_NAME = "USDA FoodData Central JSON dump"
FOOD_LIST_KEYS = (
    "FoundationFoods",
    "SRLegacyFoods",
    "SurveyFoods",
    "BrandedFoods",
    "SampleFoods",
    "foods",
    "Foods",
)


@dataclass(frozen=True)
class ImportResult:
    status: str
    foods_imported: int
    nutrients_imported: int
    portions_imported: int
    error_message: str | None = None


def _json_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == ".json":
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.json"))
    return []


def _source_version(files: list[Path]) -> str:
    if not files:
        return "missing"
    latest_mtime = max(file.stat().st_mtime for file in files)
    return f"files={len(files)};latest_mtime={latest_mtime:.0f}"


def _iter_food_records(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return

    if not isinstance(payload, dict):
        return

    for key in FOOD_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item

    if "fdcId" in payload or "fdc_id" in payload:
        yield payload


def _food_category(food: dict[str, Any]) -> tuple[int | None, str | None]:
    category = food.get("foodCategory") or food.get("wweiaFoodCategory")
    if isinstance(category, dict):
        category_id = category.get("id") or category.get("code")
        description = category.get("description")
        try:
            return int(category_id), str(description) if description else None
        except (TypeError, ValueError):
            return None, str(description) if description else None

    category_id = food.get("foodCategoryId")
    try:
        return int(category_id), None
    except (TypeError, ValueError):
        return None, None


def _nutrient_info(food_nutrient: dict[str, Any]) -> tuple[int | None, str | None, str | None, str | None]:
    nutrient = food_nutrient.get("nutrient")
    if isinstance(nutrient, dict):
        nutrient_id = nutrient.get("id")
        number = nutrient.get("number")
        name = nutrient.get("name")
        unit_name = nutrient.get("unitName")
    else:
        nutrient_id = food_nutrient.get("nutrientId")
        number = food_nutrient.get("nutrientNumber")
        name = food_nutrient.get("nutrientName")
        unit_name = food_nutrient.get("unitName")

    try:
        parsed_id = int(nutrient_id)
    except (TypeError, ValueError):
        parsed_id = None

    return (
        parsed_id,
        str(number) if number is not None else None,
        str(name) if name else None,
        str(unit_name) if unit_name else None,
    )


def _portion_unit(portion: dict[str, Any]) -> str | None:
    measure_unit = portion.get("measureUnit")
    if isinstance(measure_unit, dict):
        name = measure_unit.get("name") or measure_unit.get("abbreviation")
        return str(name) if name else None
    name = portion.get("measureUnitName") or portion.get("unit") or portion.get("measureUnit")
    return str(name) if name else None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def import_usda_dump(connection: sqlite3.Connection, source_path: Path, import_id: int | None = None) -> ImportResult:
    initialize_database(connection)
    files = _json_files(source_path)
    source_version = _source_version(files)

    if import_id is None:
        import_id = record_import_started(connection, SOURCE_NAME, str(source_path), source_version)
    else:
        update_import_status(
            connection,
            import_id,
            "running",
            source_path=str(source_path),
            source_version=source_version,
            error_message=None,
        )

    if not files:
        error = f"No JSON files found at {source_path}"
        update_import_status(connection, import_id, "failed", error_message=error, completed=True)
        return ImportResult("failed", 0, 0, 0, error)

    foods_imported = 0
    nutrients_imported: set[int] = set()
    portions_imported = 0

    try:
        with connection:
            connection.execute("DELETE FROM food_portions")
            connection.execute("DELETE FROM food_nutrients")
            connection.execute("DELETE FROM foods")
            connection.execute("DELETE FROM nutrients")
            connection.execute("DELETE FROM food_categories")

            for file in files:
                payload = json.loads(file.read_text(encoding="utf-8"))
                for food in _iter_food_records(payload):
                    fdc_id = food.get("fdcId") or food.get("fdc_id")
                    description = food.get("description") or food.get("lowercaseDescription")
                    if fdc_id is None or not description:
                        continue

                    fdc_id = int(fdc_id)
                    description = str(description)
                    category_id, category_description = _food_category(food)
                    if category_id is not None and category_description:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO food_categories (id, description)
                            VALUES (?, ?)
                            """,
                            (category_id, category_description),
                        )

                    connection.execute(
                        """
                        INSERT OR REPLACE INTO foods
                          (fdc_id, description, data_type, food_category_id, publication_date, search_name, raw_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fdc_id,
                            description,
                            food.get("dataType"),
                            category_id,
                            food.get("publicationDate"),
                            normalize_search_text(description),
                            json.dumps(food, ensure_ascii=True),
                        ),
                    )
                    foods_imported += 1

                    for food_nutrient in food.get("foodNutrients") or []:
                        if not isinstance(food_nutrient, dict):
                            continue
                        nutrient_id, number, name, unit_name = _nutrient_info(food_nutrient)
                        amount_value = food_nutrient.get("amount")
                        if amount_value is None:
                            amount_value = food_nutrient.get("value")
                        amount = _to_float(amount_value)
                        if nutrient_id is None or name is None or unit_name is None:
                            continue
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO nutrients (id, number, name, unit_name)
                            VALUES (?, ?, ?, ?)
                            """,
                            (nutrient_id, number, name, unit_name),
                        )
                        nutrients_imported.add(nutrient_id)
                        derivation = food_nutrient.get("foodNutrientDerivation")
                        derivation_code = None
                        if isinstance(derivation, dict):
                            derivation_code = derivation.get("code")
                        connection.execute(
                            """
                            INSERT INTO food_nutrients (fdc_id, nutrient_id, amount, derivation_code)
                            VALUES (?, ?, ?, ?)
                            """,
                            (fdc_id, nutrient_id, amount, derivation_code),
                        )

                    for portion in food.get("foodPortions") or []:
                        if not isinstance(portion, dict):
                            continue
                        gram_weight = _to_float(portion.get("gramWeight"))
                        if gram_weight is None:
                            continue
                        connection.execute(
                            """
                            INSERT INTO food_portions
                              (fdc_id, amount, measure_unit_name, modifier, gram_weight)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                fdc_id,
                                _to_float(portion.get("amount")),
                                _portion_unit(portion),
                                portion.get("modifier"),
                                gram_weight,
                            ),
                        )
                        portions_imported += 1

        update_import_status(connection, import_id, "completed", completed=True)
        return ImportResult("completed", foods_imported, len(nutrients_imported), portions_imported)
    except Exception as exc:
        update_import_status(connection, import_id, "failed", error_message=str(exc), completed=True)
        return ImportResult("failed", foods_imported, len(nutrients_imported), portions_imported, str(exc))
