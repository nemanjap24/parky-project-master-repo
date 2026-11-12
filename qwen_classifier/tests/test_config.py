from __future__ import annotations

import pytest

from qwen_classifier.config import get_settings


@pytest.fixture(autouse=True)
def required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:30b")
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)


def test_default_timeout_is_120_seconds() -> None:
    assert get_settings().timeout_seconds == 120.0


def test_timeout_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "300")
    assert get_settings().timeout_seconds == 300.0


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_timeout_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError, match="OLLAMA_TIMEOUT_SECONDS"):
        get_settings()
