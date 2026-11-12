from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    model: str
    confidence_threshold: float = 0.75
    timeout_seconds: float = 120.0


def get_settings() -> Settings:
    base_url = os.getenv("OLLAMA_BASE_URL", "").strip()
    api_key = os.getenv("OLLAMA_API_KEY", "").strip()
    model = os.getenv("OLLAMA_MODEL", "").strip()
    threshold_raw = os.getenv("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.75").strip()
    timeout_raw = os.getenv("OLLAMA_TIMEOUT_SECONDS", "120").strip() or "120"

    missing = [
        key
        for key, value in (
            ("OLLAMA_BASE_URL", base_url),
            ("OLLAMA_API_KEY", api_key),
            ("OLLAMA_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    try:
        threshold = float(threshold_raw)
    except ValueError as exc:
        raise ValueError("CLASSIFICATION_CONFIDENCE_THRESHOLD must be a float") from exc

    if not 0 <= threshold <= 1:
        raise ValueError("CLASSIFICATION_CONFIDENCE_THRESHOLD must be between 0 and 1")

    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("OLLAMA_TIMEOUT_SECONDS must be a number") from exc

    if timeout <= 0:
        raise ValueError("OLLAMA_TIMEOUT_SECONDS must be greater than 0")

    return Settings(
        base_url=base_url,
        api_key=api_key,
        model=model,
        confidence_threshold=threshold,
        timeout_seconds=timeout,
    )
