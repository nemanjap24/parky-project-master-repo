import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qwen_classifier.models import ClassificationInput, ProductClassification
from scraper.config import ScraperSettings
from scraper.pipeline import ScrapingPipeline

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = datetime(2026, 10, 31, 19, 27, tzinfo=timezone.utc)


class FakeCrawler:
    def __init__(self, fixture: str = "kosik_metro_chef_pomarance.html") -> None:
        self.html = (FIXTURES / fixture).read_text(encoding="utf-8")

    async def crawl(self, url: str) -> str:
        return self.html


class FakeClassifier:
    model_name = "qwen3:30b"
    prompt_version = "test-v1"

    def __init__(self, confidence: float = 0.9) -> None:
        self.confidence = confidence
        self.received: list[ClassificationInput] = []

    def classify(
        self, products: Sequence[str | ClassificationInput], mark_needs_review: bool = False
    ) -> list[ProductClassification]:
        self.received.extend(item for item in products if isinstance(item, ClassificationInput))
        return [
            ProductClassification(
                name=self.received[-1].name,
                category="ovocie_zelenina",
                subcategory="citrusy",
                confidence=self.confidence,
                needs_review=self.confidence < 0.75 if mark_needs_review else None,
            )
        ]


def _pipeline(classifier: FakeClassifier, enabled: bool = True) -> ScrapingPipeline:
    return ScrapingPipeline(FakeCrawler(), classifier, ScraperSettings(classification_enabled=enabled), clock=lambda: NOW)


URL = "https://www.kosik.sk/p24154-metro-chef-pomarance-dzusove"


def test_classifier_receives_breadcrumb_and_result_is_stored() -> None:
    classifier = FakeClassifier()
    product = asyncio.run(_pipeline(classifier).scrape(URL))
    assert classifier.received == [
        ClassificationInput(
            name="Metro Chef Pomaranče džúsové",
            retailer_category_path=["Ovocie a zelenina", "Ovocie", "Citrusy", "Pomaranče"],
        )
    ]
    assert product.classification is not None
    assert product.classification.category == "ovocie_zelenina"
    assert product.classification.subcategory == "citrusy"
    assert product.classification.model == "qwen3:30b"
    assert product.classification.prompt_version == "test-v1"
    assert product.classification.classified_at == NOW
    assert product.scraped_at == NOW
    assert product.needs_review is False


def test_low_confidence_marks_record_for_review() -> None:
    product = asyncio.run(_pipeline(FakeClassifier(confidence=0.5)).scrape(URL))
    assert product.extraction.warnings == ["low_classification_confidence"]
    assert product.needs_review is True


def test_classification_can_be_disabled() -> None:
    classifier = FakeClassifier()
    product = asyncio.run(_pipeline(classifier, enabled=False).scrape(URL))
    assert product.classification is None
    assert classifier.received == []


def test_classifier_failure_is_clear() -> None:
    class BrokenClassifier(FakeClassifier):
        def classify(self, products, mark_needs_review=False):  # type: ignore[no-untyped-def]
            raise RuntimeError("service unavailable")

    with pytest.raises(RuntimeError, match="Product classification failed"):
        asyncio.run(_pipeline(BrokenClassifier()).scrape(URL))


def test_scrape_many_keeps_order() -> None:
    urls = [URL, URL + "?again"]
    products = asyncio.run(_pipeline(FakeClassifier(), enabled=False).scrape_many(urls))
    assert [product.url for product in products] == urls


def test_product_outside_listing_category_is_flagged() -> None:
    pipeline = _pipeline(FakeClassifier(), enabled=False)
    inside = asyncio.run(pipeline.scrape(URL, source_listing_url="https://www.kosik.sk/c2968-citrusy"))
    outside = asyncio.run(pipeline.scrape(URL, source_listing_url="https://www.kosik.sk/c3350-parky"))
    unknown = asyncio.run(pipeline.scrape(URL, source_listing_url=None))
    assert inside.retailer_category_ids == ["c2894", "c2964", "c2968", "c2969"]
    assert inside.extraction.warnings == []
    assert outside.extraction.warnings == ["outside_listing_category"]
    assert unknown.extraction.warnings == []
