from __future__ import annotations

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
                "raw": {"error": str(exc)},
            }

        try:
            from langchain_ollama import ChatOllama
        except Exception as exc:
            return {
                "response": "The langchain-ollama package is required for Deep Agents to use Ollama.",
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
            tools=build_agent_tools(self.connection),
            system_prompt=SYSTEM_PROMPT,
        )
        result = agent.invoke({"messages": [{"role": "user", "content": message}]})
        response = _extract_last_message(result)
        return {"response": response, "raw": result}


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
