import json

from app.agent.tools import build_agent_tools
from app.config import load_settings
from app.db import connect, initialize_database
from app.usda.importer import import_usda_dump


def test_agent_tools_open_independent_database_connections(tmp_path):
    fixture_path = tmp_path / "usda"
    fixture_path.mkdir()
    (fixture_path / "foundation.json").write_text(
        json.dumps(
            {
                "FoundationFoods": [
                    {
                        "fdcId": 123,
                        "description": "Oil, olive, salad or cooking",
                        "foodNutrients": [
                            {
                                "nutrient": {
                                    "id": 1008,
                                    "number": "208",
                                    "name": "Energy",
                                    "unitName": "kcal",
                                },
                                "amount": 884,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    database_path = tmp_path / "nutrition.sqlite"
    connection = connect(database_path)
    try:
        initialize_database(connection)
        import_usda_dump(connection, fixture_path)
    finally:
        connection.close()

    lookup_tool, _calculator_tool = build_agent_tools(database_path)
    result = lookup_tool("olive oil")

    assert result["matches"][0]["fdc_id"] == 123
    assert result["matches"][0]["nutrients_per_100g"]["Energy"]["amount"] == 884


def test_agent_calculator_tool_normalizes_ingredient_names(tmp_path, monkeypatch):
    fixture_path = tmp_path / "usda"
    fixture_path.mkdir()
    (fixture_path / "foundation.json").write_text(
        json.dumps(
            {
                "FoundationFoods": [
                    {
                        "fdcId": 123,
                        "description": "Oil, olive, salad or cooking",
                        "foodNutrients": [
                            {
                                "nutrient": {
                                    "id": 1008,
                                    "number": "208",
                                    "name": "Energy",
                                    "unitName": "kcal",
                                },
                                "amount": 884,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "nutrition.sqlite"
    connection = connect(database_path)
    try:
        initialize_database(connection)
        import_usda_dump(connection, fixture_path)
    finally:
        connection.close()

    class FakeNormalizer:
        def __init__(self, settings):
            self.settings = settings

        def normalize(self, ingredients):
            return [{"name": "olive oil", "quantity": 100, "unit": "gram", "original_name": "sitan sir"}]

    monkeypatch.setattr("app.agent.tools.IngredientNormalizer", FakeNormalizer)
    settings = load_settings(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "USDA_JSON_DUMP_PATH": str(tmp_path),
        }
    )
    lookup_tool, calculator_tool = build_agent_tools(settings)

    lookup = lookup_tool("sitan sir")

    assert lookup["ingredient_name"] == "olive oil"
    assert lookup["original_ingredient_name"] == "sitan sir"
    result = calculator_tool([{"name": "sitan sir", "quantity": 100, "unit": "gram"}])

    assert result["warnings"] == []
    assert result["ingredients"][0]["input_name"] == "olive oil"
    assert result["total"]["Energy"]["amount"] == 884


def test_agent_calculator_tool_preserves_original_foreign_ingredient_name(tmp_path, monkeypatch):
    fixture_path = tmp_path / "usda"
    fixture_path.mkdir()
    (fixture_path / "foundation.json").write_text(
        json.dumps(
            {
                "FoundationFoods": [
                    {
                        "fdcId": 321,
                        "description": "Cottage cheese, lowfat, 2% milkfat",
                        "foodNutrients": [
                            {
                                "nutrient": {
                                    "id": 1008,
                                    "number": "208",
                                    "name": "Energy",
                                    "unitName": "kcal",
                                },
                                "amount": 82,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "nutrition.sqlite"
    connection = connect(database_path)
    try:
        initialize_database(connection)
        import_usda_dump(connection, fixture_path)
    finally:
        connection.close()

    class FakeNormalizer:
        def __init__(self, settings):
            self.settings = settings

        def normalize(self, ingredients):
            return [{"name": "cottage cheese", "quantity": 100, "unit": "gram", "original_name": "sitan sir"}]

    monkeypatch.setattr("app.agent.tools.IngredientNormalizer", FakeNormalizer)
    settings = load_settings(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "USDA_JSON_DUMP_PATH": str(tmp_path),
        }
    )
    _lookup_tool, calculator_tool = build_agent_tools(settings)

    result = calculator_tool([{"name": "sitan sir", "quantity": 100, "unit": "gram"}])

    assert result["warnings"] == []
    assert result["ingredients"][0]["input_name"] == "cottage cheese"
    assert result["ingredients"][0]["original_name"] == "sitan sir"
    assert result["ingredients"][0]["resolved_name"] == "Cottage cheese, lowfat, 2% milkfat"


def test_agent_lookup_tool_rejects_broadened_normalized_short_ingredient(tmp_path, monkeypatch):
    fixture_path = tmp_path / "usda"
    fixture_path.mkdir()
    (fixture_path / "foundation.json").write_text(
        json.dumps(
            {
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
                ]
            }
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "nutrition.sqlite"
    connection = connect(database_path)
    try:
        initialize_database(connection)
        import_usda_dump(connection, fixture_path)
    finally:
        connection.close()

    class FakeNormalizer:
        def __init__(self, settings):
            self.settings = settings

        def normalize(self, ingredients):
            return [{"name": "bread egg", "quantity": 100, "unit": "gram", "original_name": "egg"}]

    monkeypatch.setattr("app.agent.tools.IngredientNormalizer", FakeNormalizer)
    settings = load_settings(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "USDA_JSON_DUMP_PATH": str(tmp_path),
        }
    )
    lookup_tool, _calculator_tool = build_agent_tools(settings)

    result = lookup_tool("egg")

    assert result["ingredient_name"] == "egg"
    assert result["matches"][0]["fdc_id"] == 200
    assert "bread egg" in result["warnings"][0]


def test_calculator_tool_description_tells_agent_to_pass_original_names(tmp_path):
    _lookup_tool, calculator_tool = build_agent_tools(tmp_path / "nutrition.sqlite")

    assert "Pass the original user ingredient names" in (calculator_tool.__doc__ or "")
