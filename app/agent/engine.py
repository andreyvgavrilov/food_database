from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from typing import Any

from app.agent.interaction_logs import InteractionLogger
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import build_agent_tools
from app.config import Settings


DEEPAGENTS_BUILT_IN_TOOLS = frozenset(
    {
        "write_todos",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "execute",
    }
)


class NutritionAgent:
    def __init__(self, settings: Settings, connection: sqlite3.Connection):
        self.settings = settings
        self.connection = connection
        self.logger = InteractionLogger(settings.interaction_logs_path)

    def invoke(self, message: str) -> dict[str, Any]:
        try:
            from deepagents import (
                GeneralPurposeSubagentProfile,
                HarnessProfile,
                create_deep_agent,
                register_harness_profile,
            )
        except Exception as exc:
            self.logger.write(
                "llm",
                "deepagents.import",
                {
                    "request": {"message": message, "model": self.settings.ollama_model},
                    "error": str(exc),
                },
            )
            return {
                "response": (
                    "Deep Agents is not installed or could not be imported. "
                    "Use the ingredient lookup and calculator endpoints directly until dependencies are installed."
                ),
                "tool_activity": [],
                "raw": {"error": str(exc)},
            }

        try:
            from langchain_ollama import ChatOllama
        except Exception as exc:
            self.logger.write(
                "llm",
                "langchain_ollama.import",
                {
                    "request": {"message": message, "model": self.settings.ollama_model},
                    "error": str(exc),
                },
            )
            return {
                "response": "The langchain-ollama package is required for Deep Agents to use Ollama.",
                "tool_activity": [],
                "raw": {"error": str(exc)},
            }

        headers = None
        if self.settings.ollama_api_key:
            headers = {"Authorization": f"Bearer {self.settings.ollama_api_key}"}

        model = ChatOllama(
            model=self.settings.ollama_model,
            base_url=self.settings.ollama_base_url,
            client_kwargs={"headers": headers} if headers else None,
            temperature=0,
        )

        register_harness_profile(
            "ollama",
            HarnessProfile(
                excluded_tools=DEEPAGENTS_BUILT_IN_TOOLS,
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            ),
        )

        agent = create_deep_agent(
            model=model,
            tools=build_agent_tools(self.settings),
            system_prompt=SYSTEM_PROMPT,
        )
        payload = {"messages": [{"role": "user", "content": message}]}
        try:
            result = agent.invoke(payload)
        except Exception as exc:
            self.logger.write(
                "llm",
                "deepagents.invoke",
                {
                    "request": {
                        "message": message,
                        "model": self.settings.ollama_model,
                        "base_url": self.settings.ollama_base_url,
                        "has_api_key": bool(self.settings.ollama_api_key),
                        "payload": payload,
                    },
                    "error": str(exc),
                },
            )
            raise
        language = _detect_response_language(message)
        response = _extract_last_message(result)
        self.logger.write(
            "llm",
            "deepagents.invoke",
            {
                "request": {
                    "message": message,
                    "model": self.settings.ollama_model,
                    "base_url": self.settings.ollama_base_url,
                    "has_api_key": bool(self.settings.ollama_api_key),
                    "payload": payload,
                },
                "response": _json_safe(result),
                "final_response": response,
            },
        )
        return {
            "response": response,
            "tool_activity": _extract_tool_activity(result, language=language),
            "raw": _json_safe(result),
        }


def _extract_last_message(result: Any) -> str:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                return str(last.get("content") or "")
            content = getattr(last, "content", None)
            if content:
                return str(content)
    return str(result)


def _extract_tool_activity(result: Any, language: str = "en") -> list[str]:
    if not isinstance(result, dict):
        return []

    messages = result.get("messages")
    if not isinstance(messages, list):
        return []

    activity: list[str] = []
    for message in messages:
        tool_name = _message_value(message, "name")
        if not tool_name and _message_value(message, "type") != "tool":
            continue

        content = _message_value(message, "content")
        parsed_content = _parse_tool_content(content)
        summary = _format_tool_result(str(tool_name or "tool"), parsed_content, language=language)
        if summary:
            activity.append(summary)

    return activity


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def _parse_tool_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _format_tool_result(tool_name: str, result: Any, language: str = "en") -> str | None:
    if tool_name == "get_ingredient_nutrition" and isinstance(result, dict):
        ingredient = str(result.get("ingredient_name") or "ingredient").strip()
        original_ingredient = result.get("original_ingredient_name")
        display_ingredient = f"**{ingredient}**"
        if isinstance(original_ingredient, str) and original_ingredient.strip() and original_ingredient.strip() != ingredient:
            if language == "ru":
                display_ingredient = f"**{original_ingredient.strip()}** (как **{ingredient}**)"
            else:
                display_ingredient = f"**{original_ingredient.strip()}** (as **{ingredient}**)"
        matches = result.get("matches")
        if isinstance(matches, list) and matches:
            match = matches[0]
            description = match.get("description") if isinstance(match, dict) else None
            confidence = match.get("confidence") if isinstance(match, dict) else None
            confidence_text = _format_percent(confidence)
            if language == "ru":
                return f"Проверен ингредиент {display_ingredient}, найдено соответствие **{description or 'USDA food'}**{confidence_text}."
            return f"Looked up {display_ingredient} and matched **{description or 'USDA food'}**{confidence_text}."
        if language == "ru":
            return f"Проверен ингредиент {display_ingredient}, но соответствие USDA не найдено."
        return f"Looked up {display_ingredient}, but no USDA match was found."

    if tool_name == "calculate_total_nutrition" and isinstance(result, dict):
        ingredients = result.get("ingredients")
        ingredient_count = len(ingredients) if isinstance(ingredients, list) else 0
        total = result.get("total") if isinstance(result.get("total"), dict) else {}
        per_serving = result.get("per_serving")
        warnings = result.get("warnings")
        calorie_text = _format_nutrient_amount(total, "Energy")
        protein_text = _format_nutrient_amount(total, "Protein")
        if language == "ru":
            parts = [f"Рассчитано питание для **{ingredient_count} ингредиент{'ов' if ingredient_count != 1 else 'а'}**"]
            if calorie_text:
                parts.append(f"общая калорийность **{calorie_text}**")
            if protein_text:
                parts.append(f"белки **{protein_text}**")
            summary = ", ".join(parts) + "."
            if per_serving:
                summary += " Значения на порцию доступны."
            if isinstance(warnings, list) and warnings:
                summary += " Некоторые пересчеты ингредиентов выполнены с предупреждениями."
            return summary
        parts = [f"Calculated nutrition for **{ingredient_count} ingredient{'s' if ingredient_count != 1 else ''}**"]
        if calorie_text:
            parts.append(f"total energy **{calorie_text}**")
        if protein_text:
            parts.append(f"protein **{protein_text}**")
        summary = ", ".join(parts) + "."
        if per_serving:
            summary += " Per-serving values are available."
        if isinstance(warnings, list) and warnings:
            summary += " Some ingredient conversions used fallback handling."
        return summary

    if isinstance(result, str) and result.strip():
        return f"{tool_name}: {result.strip()}"

    return None


def _format_calculation_response(result: dict[str, Any], language: str = "en") -> str:
    ingredients = result.get("ingredients") if isinstance(result.get("ingredients"), list) else []
    total = result.get("total") if isinstance(result.get("total"), dict) else {}
    per_100g = result.get("per_100g") if isinstance(result.get("per_100g"), dict) else {}
    total_weight = result.get("total_weight_grams")
    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    labels = _calculation_labels(language)

    lines = [f"## {labels['title']}"]
    if isinstance(total_weight, (int, float)):
        lines.append(f"{labels['total_weight']}: **{_format_number(float(total_weight))} g**")

    lines.extend(
        [
            "",
            f"### {labels['total']}",
            f"- {labels['calories']}: **{_format_nutrient_amount(total, 'Energy') or labels['not_available']}**",
            f"- {labels['protein']}: **{_format_nutrient_amount(total, 'Protein') or labels['not_available']}**",
            f"- {labels['fat']}: **{_format_nutrient_amount(total, 'Total lipid (fat)') or labels['not_available']}**",
            f"- {labels['carbs']}: **{_format_nutrient_amount(total, 'Carbohydrate, by difference') or labels['not_available']}**",
        ]
    )

    if per_100g:
        lines.extend(
            [
                "",
                f"### {labels['per_100g']}",
                f"- {labels['calories']}: **{_format_nutrient_amount(per_100g, 'Energy') or labels['not_available']}**",
                f"- {labels['protein']}: **{_format_nutrient_amount(per_100g, 'Protein') or labels['not_available']}**",
                f"- {labels['fat']}: **{_format_nutrient_amount(per_100g, 'Total lipid (fat)') or labels['not_available']}**",
                f"- {labels['carbs']}: **{_format_nutrient_amount(per_100g, 'Carbohydrate, by difference') or labels['not_available']}**",
            ]
        )

    if ingredients:
        lines.extend(
            [
                "",
                f"### {labels['by_ingredient']}",
                f"| {labels['ingredient']} | {labels['weight_g']} | {labels['calories']} | {labels['protein_g']} | {labels['fat_g']} | {labels['carbs_g']} |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                continue
            nutrition = ingredient.get("nutrition") if isinstance(ingredient.get("nutrition"), dict) else {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        _format_table_cell(ingredient.get("input_name") or ingredient.get("resolved_name") or "ingredient"),
                        _format_optional_number(ingredient.get("grams")),
                        _format_nutrient_number(nutrition, "Energy"),
                        _format_nutrient_number(nutrition, "Protein"),
                        _format_nutrient_number(nutrition, "Total lipid (fat)"),
                        _format_nutrient_number(nutrition, "Carbohydrate, by difference"),
                    ]
                )
                + " |"
            )

    if warnings:
        lines.append("")
        lines.append(f"{labels['warnings']}:")
        lines.extend(f"- {warning}" for warning in warnings)

    return "\n".join(lines)


def _detect_response_language(message: str) -> str:
    return "ru" if any("а" <= character.lower() <= "я" or character.lower() == "ё" for character in message) else "en"


def _calculation_labels(language: str) -> dict[str, str]:
    if language == "ru":
        return {
            "title": "Расчет питания",
            "total_weight": "Общий вес",
            "total": "Итого",
            "per_100g": "На 100 г",
            "by_ingredient": "По ингредиентам",
            "ingredient": "Ингредиент",
            "weight_g": "Вес (г)",
            "calories": "Калории",
            "protein": "Белки",
            "fat": "Жиры",
            "carbs": "Углеводы",
            "protein_g": "Белки (г)",
            "fat_g": "Жиры (г)",
            "carbs_g": "Углеводы (г)",
            "warnings": "Предупреждения",
            "not_available": "нет данных",
        }
    return {
        "title": "Nutrition calculation",
        "total_weight": "Total weight",
        "total": "Total",
        "per_100g": "Per 100 g",
        "by_ingredient": "By ingredient",
        "ingredient": "Ingredient",
        "weight_g": "Weight (g)",
        "calories": "Calories",
        "protein": "Protein",
        "fat": "Fat",
        "carbs": "Carbs",
        "protein_g": "Protein (g)",
        "fat_g": "Fat (g)",
        "carbs_g": "Carbs (g)",
        "warnings": "Warnings",
        "not_available": "not available",
    }


def _format_percent(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f" ({round(float(value) * 100)}% confidence)"


def _format_nutrient_amount(total: dict[str, Any], nutrient_name: str) -> str | None:
    nutrient = total.get(nutrient_name)
    if not isinstance(nutrient, dict):
        return None

    amount = nutrient.get("amount")
    unit = nutrient.get("unit")
    if not isinstance(amount, (int, float)):
        return None

    return f"{_format_number(float(amount))} {unit or ''}".strip()


def _format_nutrient_number(nutrition: dict[str, Any], nutrient_name: str) -> str:
    nutrient = nutrition.get(nutrient_name)
    if not isinstance(nutrient, dict):
        return "-"
    return _format_optional_number(nutrient.get("amount"))


def _format_optional_number(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return _format_number(float(value))


def _format_number(value: float) -> str:
    return f"{round(value, 2):g}"


def _format_table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"))
        except TypeError:
            return _json_safe(model_dump())
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
