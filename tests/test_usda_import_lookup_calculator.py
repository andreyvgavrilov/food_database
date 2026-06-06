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
    assert result["total"]["Energy"]["amount"] == 449.34
    assert result["per_serving"]["Energy"]["amount"] == 224.67
    assert result["total"]["Protein"]["amount"] == 62
