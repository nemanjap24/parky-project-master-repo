from __future__ import annotations

import json
from collections.abc import Sequence

import httpx

from .config import Settings, get_settings
from .models import ClassificationInput, ProductClassification
from .prompts import PROMPT_VERSION, build_classification_prompt

JSON_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "category": {
                "type": "string",
                "enum": [
                    "masove_vyrobky",
                    "mliecne_vyrobky",
                    "pekaren",
                    "ovocie_zelenina",
                    "napoje",
                    "mrazene",
                    "sladkosti",
                    "ine",
                ],
            },
            "subcategory": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["name", "category", "confidence"],
    },
}


class QwenClassifier:
    def __init__(self, settings: Settings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = http_client or httpx.Client(timeout=self.settings.timeout_seconds)

    @property
    def model_name(self) -> str:
        return self.settings.model

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION

    def classify(
        self,
        products: Sequence[str | ClassificationInput],
        mark_needs_review: bool = False,
    ) -> list[ProductClassification]:
        if not products:
            return []

        prompt = build_classification_prompt(products)
        payload = {
            "model": self.settings.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "temperature": 0,
            "options": {"temperature": 0},
            "format": JSON_SCHEMA,
        }
        headers = {"Authorization": "Bearer " + self.settings.api_key, "Content-Type": "application/json"}

        try:
            response = self._client.post(
                f"{self.settings.base_url.rstrip('/')}/api/generate",
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError("Request to Ollama timed out") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Request to Ollama failed: {exc}") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"Ollama API request failed with status {response.status_code}: {response.text}")

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("Ollama API returned invalid JSON") from exc

        raw_model_response = body.get("response")
        if not isinstance(raw_model_response, str):
            raise RuntimeError("Ollama API response missing `response` string field")

        try:
            parsed = json.loads(raw_model_response)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Invalid JSON in Qwen response") from exc

        if not isinstance(parsed, list):
            raise RuntimeError("Qwen response must be a JSON array")

        if len(parsed) < len(products):
            raise RuntimeError("Qwen returned fewer classifications than input products")
        if len(parsed) > len(products):
            raise RuntimeError("Qwen returned more classifications than input products")

        validated = [ProductClassification.model_validate(item) for item in parsed]

        if mark_needs_review:
            threshold = self.settings.confidence_threshold
            validated = [
                item.model_copy(update={"needs_review": item.confidence < threshold}) for item in validated
            ]

        return validated

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "QwenClassifier":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
