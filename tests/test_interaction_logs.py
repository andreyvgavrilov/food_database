import json
from datetime import datetime, timedelta, timezone

from app.config import load_settings


def _read_entries(logs_path):
    entries = []
    for path in logs_path.glob("*.jsonl"):
        entries.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return entries


def test_interaction_logger_writes_jsonl_and_prunes_old_logs(tmp_path):
    from app.agent.interaction_logs import InteractionLogger

    logs_path = tmp_path / "logs"
    logs_path.mkdir()
    old_log = logs_path / "interactions-old.jsonl"
    old_log.write_text("{}\n", encoding="utf-8")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    import os

    os.utime(old_log, (old_timestamp, old_timestamp))

    logger = InteractionLogger(logs_path)
    logger.write("llm", "ollama.chat", {"request": {"model": "test-model"}, "response": {"ok": True}})

    assert not old_log.exists()
    entries = _read_entries(logs_path)
    assert entries == [
        {
            "kind": "llm",
            "name": "ollama.chat",
            "payload": {"request": {"model": "test-model"}, "response": {"ok": True}},
            "timestamp": entries[0]["timestamp"],
        }
    ]


def test_ollama_client_logs_request_and_response(tmp_path, monkeypatch):
    from app.agent.ollama import OllamaClient

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"message":{"content":"[{\\"standard_english_name\\":\\"egg\\"}]"}}'

    monkeypatch.setattr("app.agent.ollama.urllib.request.urlopen", lambda request, timeout: FakeResponse())
    settings = load_settings(
        {
            "USDA_JSON_DUMP_PATH": str(tmp_path),
            "INTERACTION_LOGS_PATH": str(tmp_path / "logs"),
            "OLLAMA_API_KEY": "secret-token",
        }
    )

    result = OllamaClient(settings).chat_json("system prompt", "user prompt")

    assert result == [{"standard_english_name": "egg"}]
    entries = _read_entries(settings.interaction_logs_path)
    assert entries[0]["kind"] == "llm"
    assert entries[0]["name"] == "ollama.chat_json"
    assert entries[0]["payload"]["request"]["system_prompt"] == "system prompt"
    assert entries[0]["payload"]["request"]["user_prompt"] == "user prompt"
    assert entries[0]["payload"]["request"]["has_api_key"] is True
    assert "secret-token" not in json.dumps(entries[0])


def test_agent_logs_deepagents_interaction(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from app.agent.engine import NutritionAgent

    class FakeChatOllama:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def invoke(self, payload):
            return {"messages": [{"role": "assistant", "content": "Done"}]}

    monkeypatch.setitem(
        sys.modules,
        "deepagents",
        SimpleNamespace(
            create_deep_agent=lambda **kwargs: FakeAgent(),
            GeneralPurposeSubagentProfile=lambda **kwargs: SimpleNamespace(kwargs=kwargs),
            HarnessProfile=lambda **kwargs: SimpleNamespace(kwargs=kwargs),
            register_harness_profile=lambda key, profile: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "langchain_ollama", SimpleNamespace(ChatOllama=FakeChatOllama))
    settings = load_settings(
        {
            "USDA_JSON_DUMP_PATH": str(tmp_path),
            "INTERACTION_LOGS_PATH": str(tmp_path / "logs"),
            "OLLAMA_MODEL": "configured-model",
        }
    )

    result = NutritionAgent(settings, connection=None).invoke("100g egg")

    assert result["response"] == "Done"
    entries = _read_entries(settings.interaction_logs_path)
    assert entries[0]["kind"] == "llm"
    assert entries[0]["name"] == "deepagents.invoke"
    assert entries[0]["payload"]["request"]["message"] == "100g egg"
    assert entries[0]["payload"]["request"]["model"] == "configured-model"
    assert entries[0]["payload"]["response"]["messages"][0]["content"] == "Done"


def test_agent_tools_log_inputs_and_outputs(tmp_path, monkeypatch):
    import json

    from app.agent.tools import build_agent_tools
    from app.db import connect, initialize_database
    from app.usda.importer import import_usda_dump

    fixture_path = tmp_path / "usda"
    fixture_path.mkdir()
    (fixture_path / "foundation.json").write_text(
        json.dumps(
            {
                "FoundationFoods": [
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
            return [{"name": "egg", "quantity": 100, "unit": "gram"}]

    monkeypatch.setattr("app.agent.tools.IngredientNormalizer", FakeNormalizer)
    settings = load_settings(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "USDA_JSON_DUMP_PATH": str(tmp_path),
            "INTERACTION_LOGS_PATH": str(tmp_path / "logs"),
        }
    )

    lookup_tool, calculator_tool = build_agent_tools(settings)
    lookup_tool("egg")
    calculator_tool([{"name": "egg", "quantity": 100, "unit": "gram"}])

    entries = _read_entries(settings.interaction_logs_path)
    tool_entries = [entry for entry in entries if entry["kind"] == "tool"]
    assert [entry["name"] for entry in tool_entries] == [
        "get_ingredient_nutrition",
        "calculate_total_nutrition",
    ]
    assert tool_entries[0]["payload"]["input"]["ingredient_name"] == "egg"
    assert tool_entries[0]["payload"]["output"]["matches"][0]["fdc_id"] == 200
    assert tool_entries[1]["payload"]["input"]["ingredients"][0]["name"] == "egg"
    assert tool_entries[1]["payload"]["output"]["total"]["Energy"]["amount"] == 143


def test_gitignore_ignores_interaction_logs_folder():
    assert "logs/" in __import__("pathlib").Path(".gitignore").read_text(encoding="utf-8").splitlines()
