from app.agent.engine import _extract_tool_activity, _format_calculation_response


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


def test_format_calculation_response_uses_tool_totals_and_per_100g():
    response = _format_calculation_response(
        {
            "ingredients": [
                {
                    "input_name": "olive oil",
                    "grams": 13.5,
                    "nutrition": {
                        "Energy": {"amount": 119.34, "unit": "kcal"},
                        "Protein": {"amount": 0, "unit": "g"},
                        "Total lipid (fat)": {"amount": 13.5, "unit": "g"},
                    },
                },
                {
                    "input_name": "chicken breast",
                    "grams": 200,
                    "nutrition": {
                        "Energy": {"amount": 330, "unit": "kcal"},
                        "Protein": {"amount": 62, "unit": "g"},
                    },
                },
            ],
            "total_weight_grams": 213.5,
            "total": {
                "Energy": {"amount": 449.34, "unit": "kcal"},
                "Protein": {"amount": 62, "unit": "g"},
                "Total lipid (fat)": {"amount": 13.5, "unit": "g"},
            },
            "per_100g": {
                "Energy": {"amount": 210.4637, "unit": "kcal"},
                "Protein": {"amount": 29.0398, "unit": "g"},
                "Total lipid (fat)": {"amount": 6.3232, "unit": "g"},
            },
        }
    )

    assert "Total weight: **213.5 g**" in response
    assert "- Calories: **449.34 kcal**" in response
    assert "- Calories: **210.46 kcal**" in response
    assert "| olive oil | 13.5 | 119.34 | 0 | 13.5 | - |" in response
