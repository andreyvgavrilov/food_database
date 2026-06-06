from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import build_agent_tools
from app.config import Settings


class NutritionAgent:
    def __init__(self, settings: Settings, connection: sqlite3.Connection):
        self.settings = settings
        self.connection = connection

    def invoke(self, message: str) -> dict[str, Any]:
        try:
            from deepagents import create_deep_agent
        except Exception as exc:
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

        agent = create_deep_agent(
            model=model,
            tools=build_agent_tools(self.settings.database_path),
            system_prompt=SYSTEM_PROMPT,
        )
        result = agent.invoke({"messages": [{"role": "user", "content": message}]})
        response = _extract_last_message(result)
        return {"response": response, "tool_activity": _extract_tool_activity(result), "raw": result}


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


def _extract_tool_activity(result: Any) -> list[str]:
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
        summary = _format_tool_result(str(tool_name or "tool"), parsed_content)
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


def _format_tool_result(tool_name: str, result: Any) -> str | None:
    if tool_name == "get_ingredient_nutrition" and isinstance(result, dict):
        ingredient = str(result.get("ingredient_name") or "ingredient").strip()
        matches = result.get("matches")
        if isinstance(matches, list) and matches:
            match = matches[0]
            description = match.get("description") if isinstance(match, dict) else None
            confidence = match.get("confidence") if isinstance(match, dict) else None
            confidence_text = _format_percent(confidence)
            return f"Looked up **{ingredient}** and matched **{description or 'USDA food'}**{confidence_text}."
        return f"Looked up **{ingredient}**, but no USDA match was found."

    if tool_name == "calculate_total_nutrition" and isinstance(result, dict):
        ingredients = result.get("ingredients")
        ingredient_count = len(ingredients) if isinstance(ingredients, list) else 0
        total = result.get("total") if isinstance(result.get("total"), dict) else {}
        per_serving = result.get("per_serving")
        warnings = result.get("warnings")
        calorie_text = _format_nutrient_amount(total, "Energy")
        protein_text = _format_nutrient_amount(total, "Protein")
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

    display_amount = round(float(amount), 2)
    return f"{display_amount:g} {unit or ''}".strip()
