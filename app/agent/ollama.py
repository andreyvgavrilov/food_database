from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.agent.interaction_logs import InteractionLogger
from app.config import Settings


NORMALIZATION_PROMPT = """Convert recipe ingredients to standard English names for USDA FoodData Central lookup.
Return JSON only, with this shape:
[
  {"original_name": "...", "standard_english_name": "...", "quantity": 1, "unit": "gram"}
]
Preserve numeric quantities and units when present.
Translate non-English, transliterated, and regional ingredient names to the closest common USDA-searchable English food identity. If there is no exact direct representation, choose the closest generic food, not a branded or compound prepared dish.
Do not add unrelated product words: "egg" stays "egg", never "bread egg".
Examples:
- "sitan sir" -> "cottage cheese"
- "tomates" -> "tomato"
- "huile d'olive" -> "olive oil"
Do not add commentary.
"""


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = InteractionLogger(settings.interaction_logs_path)

    def chat_json(self, system_prompt: str, user_prompt: str) -> Any:
        url = self.settings.ollama_base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": self.settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.settings.ollama_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ollama_api_key}"

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.settings.ollama_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.logger.write(
                "llm",
                "ollama.chat_json",
                {
                    "request": _loggable_request(
                        settings=self.settings,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        format="json",
                    ),
                    "error": str(exc),
                },
            )
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        content = data.get("message", {}).get("content")
        if not content:
            self.logger.write(
                "llm",
                "ollama.chat_json",
                {
                    "request": _loggable_request(
                        settings=self.settings,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        format="json",
                    ),
                    "raw_response": data,
                    "error": "Ollama response did not include message content",
                },
            )
            raise RuntimeError("Ollama response did not include message content")
        try:
            parsed = _parse_json_content(str(content))
        except RuntimeError as exc:
            self.logger.write(
                "llm",
                "ollama.chat_json",
                {
                    "request": _loggable_request(
                        settings=self.settings,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        format="json",
                    ),
                    "raw_response": data,
                    "error": str(exc),
                },
            )
            raise
        self.logger.write(
            "llm",
            "ollama.chat_json",
            {
                "request": _loggable_request(
                    settings=self.settings,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    format="json",
                ),
                "raw_response": data,
                "parsed_response": parsed,
            },
        )
        return parsed


def _loggable_request(settings: Settings, system_prompt: str, user_prompt: str, format: str) -> dict[str, Any]:
    return {
        "url": settings.ollama_base_url.rstrip("/") + "/api/chat",
        "model": settings.ollama_model,
        "timeout_seconds": settings.ollama_timeout_seconds,
        "has_api_key": bool(settings.ollama_api_key),
        "format": format,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def _parse_json_content(content: str) -> Any:
    for candidate in _json_candidates(content):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Ollama returned invalid JSON: {content}")


def _json_candidates(content: str) -> list[str]:
    stripped = content.strip()
    candidates = [stripped]
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        fenced = "\n".join(lines).strip()
        if fenced:
            candidates.append(fenced)

    for opener, closer in (("[", "]"), ("{", "}")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            candidates.append(stripped[start : end + 1])

    return candidates


class IngredientNormalizer:
    def __init__(self, settings: Settings):
        self.client = OllamaClient(settings)

    def normalize(self, ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prompt = json.dumps(ingredients, ensure_ascii=False)
        normalized = self.client.chat_json(NORMALIZATION_PROMPT, prompt)
        if not isinstance(normalized, list):
            raise RuntimeError("Ingredient normalization did not return a JSON array")

        output: list[dict[str, Any]] = []
        for item in normalized:
            if not isinstance(item, dict):
                continue
            output.append(
                {
                    "name": item.get("standard_english_name") or item.get("name") or item.get("original_name"),
                    "quantity": item.get("quantity"),
                    "unit": item.get("unit") or "gram",
                    "original_name": item.get("original_name"),
                }
            )
        return output
