import json

from app.config import load_settings
from app.db import connect, initialize_database
from app.usda.importer import import_usda_dump


class FakeFastMCP:
    def __init__(self, name):
        self.name = name
        self.tools = {}
        self.run_calls = []

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register

    def run(self):
        self.run_calls.append({})


def _settings_with_fixture(tmp_path):
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
                        ],
                        "foodPortions": [
                            {
                                "amount": 1,
                                "measureUnit": {"name": "tablespoon"},
                                "gramWeight": 13.5,
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

    return load_settings(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "USDA_JSON_DUMP_PATH": str(fixture_path),
        }
    )


def test_mcp_server_exposes_nutrition_tools(tmp_path):
    from app.mcp_server import create_mcp_server

    server = create_mcp_server(settings=_settings_with_fixture(tmp_path), mcp_factory=FakeFastMCP)

    assert server.name == "AI Nutrition Agent"
    assert set(server.tools) == {"get_ingredient_nutrition", "calculate_total_nutrition"}


def test_mcp_lookup_tool_uses_application_tool_behavior(tmp_path):
    from app.mcp_server import create_mcp_server

    server = create_mcp_server(settings=_settings_with_fixture(tmp_path), mcp_factory=FakeFastMCP)

    result = server.tools["get_ingredient_nutrition"]("olive oil")

    assert result["ingredient_name"] == "olive oil"
    assert result["matches"][0]["fdc_id"] == 123
    assert result["matches"][0]["nutrients_per_100g"]["Energy"]["amount"] == 884


def test_mcp_calculator_tool_uses_application_tool_behavior(tmp_path):
    from app.mcp_server import create_mcp_server

    server = create_mcp_server(settings=_settings_with_fixture(tmp_path), mcp_factory=FakeFastMCP)

    result = server.tools["calculate_total_nutrition"](
        [{"name": "olive oil", "quantity": 1, "unit": "tablespoon"}],
        servings=2,
    )

    assert result["ingredients"][0]["grams"] == 13.5
    assert result["total"]["Energy"]["amount"] == 119.34
    assert result["per_serving"]["Energy"]["amount"] == 59.67
