"""Scraping and optional classification orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Protocol

from qwen_classifier.models import ClassificationInput, ProductClassification

from .config import ScraperSettings, get_scraper_settings
from .crawler import KosikCrawler
from .extraction import extract_product
from .models import Classification, ProductObservation


class Classifier(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    def classify(
        self,
        products: Sequence[str | ClassificationInput],
        mark_needs_review: bool = False,
    ) -> list[ProductClassification]: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScrapingPipeline:
    def __init__(
        self,
        crawler: KosikCrawler | None = None,
        classifier: Classifier | None = None,
        settings: ScraperSettings | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.settings = settings or get_scraper_settings()
        self.crawler = crawler or KosikCrawler(self.settings)
        self.classifier = classifier
        self.clock = clock

    async def scrape(self, url: str, classify: bool | None = None) -> ProductObservation:
        product = extract_product(await self.crawler.crawl(url), url, scraped_at=self.clock())
        enabled = self.settings.classification_enabled if classify is None else classify
        if not enabled:
            return product
        return self.classify_product(product)

    def classify_product(self, product: ProductObservation) -> ProductObservation:
        """Attach a classification based on the retailer breadcrumb (and name).

        A classification below the confidence threshold adds the
        ``low_classification_confidence`` warning, which makes ``needs_review`` true.
        """

        if self.classifier is None:
            raise RuntimeError("Classification is enabled but no classifier was provided")
        if not product.name:
            raise RuntimeError(f"Cannot classify product without a name: {product.url}")
        item = ClassificationInput(name=product.name, retailer_category_path=product.retailer_category_path)
        try:
            result = self.classifier.classify([item], mark_needs_review=True)
        except Exception as exc:
            raise RuntimeError(f"Product classification failed: {exc}") from exc
        if len(result) != 1:
            raise RuntimeError("Classifier returned an unexpected number of results")
        answer = result[0]
        classification = Classification(
            category=answer.category,
            subcategory=answer.subcategory,
            confidence=answer.confidence,
            model=self.classifier.model_name,
            prompt_version=self.classifier.prompt_version,
            classified_at=self.clock(),
        )
        warnings = list(product.extraction.warnings)
        if answer.needs_review and "low_classification_confidence" not in warnings:
            warnings.append("low_classification_confidence")
        return product.model_copy(
            update={
                "classification": classification,
                "extraction": product.extraction.model_copy(update={"warnings": warnings}),
            }
        )

    async def scrape_many(self, urls: Sequence[str], classify: bool | None = None) -> list[ProductObservation]:
        return [await self.scrape(url, classify=classify) for url in urls]
