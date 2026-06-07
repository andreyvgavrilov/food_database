from app.agent.ollama import IngredientNormalizer
from app.agent.ollama import OllamaClient
from app.config import load_settings


class FakeClient:
    def chat_json(self, system_prompt, user_prompt):
        return [
            {
                "original_name": "tomates",
                "standard_english_name": "tomato",
                "quantity": 2,
                "unit": "item",
            }
        ]


def test_ingredient_normalizer_parses_response(tmp_path):
    normalizer = IngredientNormalizer(load_settings({"USDA_JSON_DUMP_PATH": str(tmp_path)}))
    normalizer.client = FakeClient()

    result = normalizer.normalize([{"name": "tomates", "quantity": 2, "unit": "item"}])

    assert result == [
        {
            "name": "tomato",
            "quantity": 2,
            "unit": "item",
            "original_name": "tomates",
        }
    ]


def test_ollama_client_accepts_fenced_json_response(tmp_path, monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return (
                b'{"message":{"content":"```json\\n'
                b'[{\\\"original_name\\\":\\\"sitan sir\\\",'
                b'\\\"standard_english_name\\\":\\\"cottage cheese\\\",'
                b'\\\"quantity\\\":100,\\\"unit\\\":\\\"gram\\\"}]\\n```"}}'
            )

    monkeypatch.setattr("app.agent.ollama.urllib.request.urlopen", lambda request, timeout: FakeResponse())
    client = OllamaClient(load_settings({"USDA_JSON_DUMP_PATH": str(tmp_path)}))

    result = client.chat_json("system", "user")

    assert result == [
        {
            "original_name": "sitan sir",
            "standard_english_name": "cottage cheese",
            "quantity": 100,
            "unit": "gram",
        }
    ]
