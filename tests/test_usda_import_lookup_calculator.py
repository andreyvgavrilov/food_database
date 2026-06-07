import json

from app.db import connect, initialize_database
from app.nutrition.calculator import NutritionCalculator
from app.usda.importer import import_usda_dump
from app.usda.lookup import IngredientLookup
from app.usda.units import convert_to_grams


def _write_fixture(path):
    path.mkdir()
    payload = {
        "FoundationFoods": [
            {
                "fdcId": 123,
                "description": "Oil, olive, salad or cooking",
                "dataType": "Foundation",
                "foodCategory": {"id": 1, "description": "Fats and Oils"},
                "publicationDate": "2024-01-01",
                "foodNutrients": [
                    {
                        "nutrient": {
                            "id": 1008,
                            "number": "208",
                            "name": "Energy",
                            "unitName": "kcal",
                        },
                        "amount": 884,
                    },
                    {
                        "nutrient": {
                            "id": 1003,
                            "number": "203",
                            "name": "Protein",
                            "unitName": "g",
                        },
                        "amount": 0,
                    },
                    {
                        "nutrient": {
                            "id": 1004,
                            "number": "204",
                            "name": "Total lipid (fat)",
                            "unitName": "g",
                        },
                        "amount": 100,
                    },
                ],
                "foodPortions": [
                    {
                        "amount": 1,
                        "measureUnit": {"name": "tablespoon"},
                        "gramWeight": 13.5,
                    }
                ],
            },
            {
                "fdcId": 456,
                "description": "Chicken breast, cooked, roasted",
                "dataType": "Foundation",
                "foodCategory": {"id": 2, "description": "Poultry Products"},
                "publicationDate": "2024-01-01",
                "foodNutrients": [
                    {
                        "nutrient": {
                            "id": 1008,
                            "number": "208",
                            "name": "Energy",
                            "unitName": "kcal",
                        },
                        "amount": 165,
                    },
                    {
                        "nutrient": {
                            "id": 1003,
                            "number": "203",
                            "name": "Protein",
                            "unitName": "g",
                        },
                        "amount": 31,
                    },
                ],
                "foodPortions": [],
            },
        ]
    }
    (path / "foundation.json").write_text(json.dumps(payload), encoding="utf-8")


def _connection(tmp_path):
    db = connect(tmp_path / "nutrition.sqlite")
    initialize_database(db)
    return db


def test_import_usda_dump_and_lookup(tmp_path):
    fixture_path = tmp_path / "usda"
    _write_fixture(fixture_path)
    db = _connection(tmp_path)

    result = import_usda_dump(db, fixture_path)

    assert result.status == "completed"
    assert result.foods_imported == 2
    assert result.nutrients_imported == 3
    assert result.portions_imported == 1

    lookup = IngredientLookup(db).get_ingredient_nutrition("olive oil", "Fats and Oils")

    assert lookup["matches"][0]["fdc_id"] == 123
    assert lookup["matches"][0]["nutrients_per_100g"]["Energy"]["amount"] == 884
    assert lookup["matches"][0]["portion_conversions"][0]["gram_weight"] == 13.5


def test_lookup_uses_token_match_not_substring_match(tmp_path):
    fixture_path = tmp_path / "usda"
    fixture_path.mkdir()
    payload = {
        "FoundationFoods": [
            {
                "fdcId": 100,
                "description": "Eggnog",
                "foodNutrients": [
                    {
                        "nutrient": {
                            "id": 1008,
                            "number": "208",
                            "name": "Energy",
                            "unitName": "kcal",
                        },
                        "amount": 88,
                    }
                ],
            },
            {
                "fdcId": 200,
                "description": "Egg, whole, raw, fresh",
                "foodNutrients": [
                    {
                        "nutrient": {
                            "id": 1008,
                            "number": "208",
                            "name": "Energy",
                            "unitName": "kcal",
                        },
                        "amount": 143,
                    }
                ],
            },
        ]
    }
    (fixture_path / "foundation.json").write_text(json.dumps(payload), encoding="utf-8")
    db = _connection(tmp_path)
    import_usda_dump(db, fixture_path)

    lookup = IngredientLookup(db).get_ingredient_nutrition("egg", max_results=5)

    assert [match["fdc_id"] for match in lookup["matches"]] == [200]


def test_lookup_prefers_generic_single_ingredient_over_compound_food(tmp_path):
    fixture_path = tmp_path / "usda"
    fixture_path.mkdir()
    payload = {
        "FoundationFoods": [
            {
                "fdcId": 100,
                "description": "Bread, egg",
                "foodNutrients": [
                    {
                        "nutrient": {
                            "id": 1008,
                            "number": "208",
                            "name": "Energy",
                            "unitName": "kcal",
                        },
                        "amount": 287,
                    }
                ],
            },
            {
                "fdcId": 200,
                "description": "Egg, whole, raw",
                "foodNutrients": [
                    {
                        "nutrient": {
                            "id": 1008,
                            "number": "208",
                            "name": "Energy",
                            "unitName": "kcal",
                        },
                        "amount": 143,
                    }
                ],
            },
            {
                "fdcId": 300,
                "description": "Egg burrito",
                "foodNutrients": [
                    {
                        "nutrient": {
                            "id": 1008,
                            "number": "208",
                            "name": "Energy",
                            "unitName": "kcal",
                        },
                        "amount": 180,
                    }
                ],
            },
        ]
    }
    (fixture_path / "foundation.json").write_text(json.dumps(payload), encoding="utf-8")
    db = _connection(tmp_path)
    import_usda_dump(db, fixture_path)

    lookup = IngredientLookup(db).get_ingredient_nutrition("egg", max_results=3)

    assert lookup["matches"][0]["fdc_id"] == 200
    assert lookup["matches"][0]["description"] == "Egg, whole, raw"


def test_convert_to_grams_from_metric_and_portion():
    assert convert_to_grams(2, "kilogram", []).grams == 2000

    conversion = convert_to_grams(
        2,
        "tablespoons",
        [{"amount": 1, "unit": "tablespoon", "gram_weight": 13.5}],
    )

    assert conversion.grams == 27
    assert conversion.warning is None


def test_calculate_total_nutrition(tmp_path):
    fixture_path = tmp_path / "usda"
    _write_fixture(fixture_path)
    db = _connection(tmp_path)
    import_usda_dump(db, fixture_path)

    result = NutritionCalculator(db).calculate_total_nutrition(
        [
            {"name": "olive oil", "quantity": 1, "unit": "tablespoon"},
            {"name": "chicken breast", "quantity": 200, "unit": "gram"},
        ],
        servings=2,
    )

    assert result["ingredients"][0]["grams"] == 13.5
    assert result["ingredients"][1]["grams"] == 200
    assert result["total_weight_grams"] == 213.5
    assert result["total"]["Energy"]["amount"] == 449.34
    assert result["per_100g"]["Energy"]["amount"] == 210.4637
    assert result["per_100g"]["Protein"]["amount"] == 29.0398
    assert result["per_serving"]["Energy"]["amount"] == 224.67
    assert result["total"]["Protein"]["amount"] == 62


def test_calculate_total_nutrition_accepts_agent_argument_aliases(tmp_path):
    fixture_path = tmp_path / "usda"
    _write_fixture(fixture_path)
    db = _connection(tmp_path)
    import_usda_dump(db, fixture_path)

    result = NutritionCalculator(db).calculate_total_nutrition(
        [
            {"ingredient_name": "olive oil", "grams": 13.5},
            {"input_name": "chicken breast", "amount": 200, "unit": "g"},
        ]
    )

    assert result["warnings"] == []
    assert result["ingredients"][0]["input_name"] == "olive oil"
    assert result["ingredients"][1]["input_name"] == "chicken breast"
    assert result["total_weight_grams"] == 213.5
    assert result["total"]["Energy"]["amount"] == 449.34
    assert result["per_100g"]["Energy"]["amount"] == 210.4637


def test_calculate_total_nutrition_reports_missing_names_without_lookup(tmp_path):
    db = _connection(tmp_path)

    result = NutritionCalculator(db).calculate_total_nutrition([{"quantity": 100, "unit": "gram"}])

    assert result["warnings"] == ["Ingredient name is missing."]
    assert result["ingredients"][0]["warnings"] == ["Ingredient name is missing."]
    assert result["ingredients"][0]["input_name"] == ""
    assert result["total"] == {}
