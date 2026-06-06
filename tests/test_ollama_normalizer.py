from app.agent.ollama import IngredientNormalizer
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
