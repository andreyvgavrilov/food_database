from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.config import Settings


NORMALIZATION_PROMPT = """Convert recipe ingredients to standard English names.
Return JSON only, with this shape:
[
  {"original_name": "...", "standard_english_name": "...", "quantity": 1, "unit": "gram"}
]
Preserve numeric quantities and units when present. Do not add commentary.
"""


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings

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
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        content = data.get("message", {}).get("content")
        if not content:
            raise RuntimeError("Ollama response did not include message content")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned invalid JSON: {content}") from exc


class IngredientNormalizer:
    def __init__(self, settings: Settings):
        self.client = OllamaClient(settings)

    def normalize(self, ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prompt = json.dumps(ingredients, ensure_ascii=True)
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
