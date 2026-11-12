import httpx
import pytest

from qwen_classifier.client import QwenClassifier
from qwen_classifier.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        base_url="https://example.test/ollama",
        api_key="test-key",
        model="qwen3:30b",
        confidence_threshold=0.75,
        timeout_seconds=2,
    )


def test_classify_success_and_needs_review_marking(settings: Settings) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["json"] = __import__("json").loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "response": '[{"name":"A","category":"ine","confidence":0.7},{"name":"B","category":"napoje","confidence":0.95}]'
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = QwenClassifier(settings=settings, http_client=client)

    result = classifier.classify(["A", "B"], mark_needs_review=True)

    assert len(result) == 2
    assert result[0].needs_review is True
    assert result[1].needs_review is False
    assert captured["url"] == "https://example.test/ollama/api/generate"
    assert isinstance(captured["auth"], str)
    assert captured["auth"].startswith("Bearer ")
    assert captured["auth"].endswith(settings.api_key)
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen3:30b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["temperature"] == 0
    assert payload["format"]["type"] == "array"


def test_invalid_json_in_qwen_response(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "not-json"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = QwenClassifier(settings=settings, http_client=client)

    with pytest.raises(RuntimeError, match="Invalid JSON in Qwen response"):
        classifier.classify(["A"])


def test_http_500_error(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = QwenClassifier(settings=settings, http_client=client)

    with pytest.raises(RuntimeError, match="status 500"):
        classifier.classify(["A"])


def test_timeout_error(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = QwenClassifier(settings=settings, http_client=client)

    with pytest.raises(RuntimeError, match="timed out"):
        classifier.classify(["A"])


def test_fewer_objects_than_input(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": '[{"name":"A","category":"ine","confidence":0.7}]'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = QwenClassifier(settings=settings, http_client=client)

    with pytest.raises(RuntimeError, match="Qwen returned fewer classifications than input products"):
        classifier.classify(["A", "B"])


def test_more_objects_than_input(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": '[{"name":"A","category":"ine","confidence":0.7},{"name":"B","category":"napoje","confidence":0.8}]'
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    classifier = QwenClassifier(settings=settings, http_client=client)

    with pytest.raises(RuntimeError, match="Qwen returned more classifications than input products"):
        classifier.classify(["A"])


def test_classify_accepts_breadcrumb_inputs_and_exposes_metadata(settings: Settings) -> None:
    from qwen_classifier.models import ClassificationInput
    from qwen_classifier.prompts import PROMPT_VERSION

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["prompt"] = __import__("json").loads(request.content.decode("utf-8"))["prompt"]
        return httpx.Response(200, json={"response": '[{"name":"Párky","category":"masove_vyrobky","confidence":0.9}]'})

    classifier = QwenClassifier(settings=settings, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = classifier.classify([ClassificationInput(name="Párky", retailer_category_path=["Údeniny a lahôdky", "Párky"])])

    assert result[0].category == "masove_vyrobky"
    assert "retailer category: Údeniny a lahôdky > Párky" in captured["prompt"]
    assert classifier.model_name == "qwen3:30b"
    assert classifier.prompt_version == PROMPT_VERSION
