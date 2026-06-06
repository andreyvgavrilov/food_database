from app.agent.engine import _extract_tool_activity


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
