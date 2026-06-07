import sys
from types import SimpleNamespace

from app.agent.engine import NutritionAgent, _extract_tool_activity
from app.agent.prompts import SYSTEM_PROMPT
from app.config import load_settings


def test_extract_tool_activity_formats_lookup_result():
    result = {
        "messages": [
            {"role": "user", "content": "olive oil"},
            {
                "type": "tool",
                "name": "get_ingredient_nutrition",
                "content": (
                    '{"ingredient_name":"olive oil","matches":[{"description":'
                    '"Oil, olive, salad or cooking","confidence":0.9}]}'
                ),
            },
        ]
    }

    assert _extract_tool_activity(result) == [
        "Looked up **olive oil** and matched **Oil, olive, salad or cooking** (90% confidence)."
    ]


def test_extract_tool_activity_formats_calculation_result():
    result = {
        "messages": [
            {
                "type": "tool",
                "name": "calculate_total_nutrition",
                "content": {
                    "ingredients": [{"input_name": "olive oil"}, {"input_name": "chicken breast"}],
                    "total": {
                        "Energy": {"amount": 449.34, "unit": "kcal"},
                        "Protein": {"amount": 62, "unit": "g"},
                    },
                    "per_serving": {"Energy": {"amount": 224.67, "unit": "kcal"}},
                    "warnings": ["one warning"],
                },
            }
        ]
    }

    assert _extract_tool_activity(result) == [
        (
            "Calculated nutrition for **2 ingredients**, total energy **449.34 kcal**, "
            "protein **62 g**. Per-serving values are available. "
            "Some ingredient conversions used fallback handling."
        )
    ]


def test_extract_tool_activity_preserves_russian_request_language():
    result = {
        "messages": [
            {
                "type": "tool",
                "name": "get_ingredient_nutrition",
                "content": '{"ingredient_name":"egg","matches":[]}',
            }
        ]
    }

    assert _extract_tool_activity(result, language="ru") == [
        "Проверен ингредиент **egg**, но соответствие USDA не найдено."
    ]


def test_extract_tool_activity_shows_normalized_lookup_name():
    result = {
        "messages": [
            {
                "type": "tool",
                "name": "get_ingredient_nutrition",
                "content": {
                    "ingredient_name": "olive oil",
                    "original_ingredient_name": "sitan sir",
                    "matches": [{"description": "Oil, olive, salad or cooking", "confidence": 0.9}],
                },
            }
        ]
    }

    assert _extract_tool_activity(result) == [
        "Looked up **sitan sir** (as **olive oil**) and matched **Oil, olive, salad or cooking** (90% confidence)."
    ]


def test_agent_uses_llm_final_answer_after_tool_calls(monkeypatch, tmp_path):
    registered_profiles = []
    created_agents = []

    class FakeHarnessProfile:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeGeneralPurposeSubagentProfile:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeChatOllama:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def invoke(self, payload):
            return {
                "messages": [
                    {"role": "user", "content": payload["messages"][0]["content"]},
                    {
                        "type": "tool",
                        "name": "calculate_total_nutrition",
                        "content": {
                            "ingredients": [{"input_name": "egg", "grams": 100}],
                            "total_weight_grams": 100,
                            "total": {"Energy": {"amount": 143, "unit": "kcal"}},
                            "per_100g": {"Energy": {"amount": 143, "unit": "kcal"}},
                            "warnings": [],
                        },
                    },
                    {"role": "assistant", "content": "LLM-owned final answer with the nutrition table."},
                ]
            }

    def fake_register_harness_profile(key, profile):
        registered_profiles.append((key, profile))

    def fake_create_deep_agent(**kwargs):
        created_agents.append(kwargs)
        return FakeAgent()

    monkeypatch.setitem(
        sys.modules,
        "deepagents",
        SimpleNamespace(
            create_deep_agent=fake_create_deep_agent,
            GeneralPurposeSubagentProfile=FakeGeneralPurposeSubagentProfile,
            HarnessProfile=FakeHarnessProfile,
            register_harness_profile=fake_register_harness_profile,
        ),
    )
    monkeypatch.setitem(sys.modules, "langchain_ollama", SimpleNamespace(ChatOllama=FakeChatOllama))

    settings = load_settings(
        {
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'nutrition.sqlite').as_posix()}",
            "OLLAMA_BASE_URL": "http://ollama.example.test",
            "OLLAMA_MODEL": "configured-model",
            "USDA_JSON_DUMP_PATH": str(tmp_path),
        }
    )

    result = NutritionAgent(settings, connection=None).invoke("100g egg")

    assert result["response"] == "LLM-owned final answer with the nutrition table."
    assert created_agents[0]["model"].kwargs["model"] == "configured-model"
    assert created_agents[0]["model"].kwargs["base_url"] == "http://ollama.example.test"
    assert registered_profiles
    assert registered_profiles[0][0] == "ollama"
    assert registered_profiles[0][1].kwargs["general_purpose_subagent"].kwargs["enabled"] is False


def test_agent_returns_json_safe_raw_messages(monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage, ToolMessage

    class FakeChatOllama:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        def invoke(self, payload):
            return {
                "messages": [
                    ToolMessage(
                        content='{"ingredient_name":"egg","matches":[]}',
                        name="get_ingredient_nutrition",
                        tool_call_id="lookup-1",
                    ),
                    AIMessage(content="No reliable match was found."),
                ]
            }

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
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'nutrition.sqlite').as_posix()}",
            "USDA_JSON_DUMP_PATH": str(tmp_path),
        }
    )

    result = NutritionAgent(settings, connection=None).invoke("egg")

    assert result["response"] == "No reliable match was found."
    assert isinstance(result["raw"]["messages"][0], dict)
    assert result["raw"]["messages"][0]["type"] == "tool"


def test_system_prompt_requires_calculator_with_original_names_for_recipe_totals():
    assert "calculate_total_nutrition exactly once" in SYSTEM_PROMPT
    assert "original user ingredient names" in SYSTEM_PROMPT
