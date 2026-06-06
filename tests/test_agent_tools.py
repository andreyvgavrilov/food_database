import json

from app.agent.tools import build_agent_tools
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
