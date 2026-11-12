"""Scraping and optional classification orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Protocol

from qwen_classifier.models import ClassificationInput, ProductClassification

from .config import ScraperSettings, get_scraper_settings
from .crawler import KosikCrawler
from .discovery import category_id_from_url
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
        run_id: str | None = None,
    ) -> None:
        self.settings = settings or get_scraper_settings()
        self.crawler = crawler or KosikCrawler(self.settings)
        self.classifier = classifier
        self.clock = clock
        self.run_id = run_id

    async def scrape(
        self,
        url: str,
        classify: bool | None = None,
        source_listing_url: str | None = None,
    ) -> ProductObservation:
        product = extract_product(await self.crawler.crawl(url), url, scraped_at=self.clock())
        product = product.model_copy(update={"run_id": self.run_id, "source_listing_url": source_listing_url})
        product = self._check_listing_category(product)
        enabled = self.settings.classification_enabled if classify is None else classify
        if not enabled:
            return product
        return self.classify_product(product)

    @staticmethod
    def _check_listing_category(product: ProductObservation) -> ProductObservation:
        """Flag products whose breadcrumb is not under the listing they were found on.

        Category pages also show recommended products from other categories; the
        product's own breadcrumb tells whether it really belongs to the listing.
        """

        listing_id = category_id_from_url(product.source_listing_url)
        if listing_id is None or not product.retailer_category_ids or listing_id in product.retailer_category_ids:
            return product
        warnings = [*product.extraction.warnings, "outside_listing_category"]
        return product.model_copy(update={"extraction": product.extraction.model_copy(update={"warnings": warnings})})

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

    async def scrape_many(
        self,
        urls: Sequence[str],
        classify: bool | None = None,
        source_listing_url: str | None = None,
        on_result: Callable[[ProductObservation], None] | None = None,
    ) -> list[ProductObservation]:
        """Scrape URLs sequentially (rate-limited by the crawler), e.g. one listing batch.

        ``on_result`` is called after each product, so results can be persisted
        before the whole batch finishes.
        """

        results: list[ProductObservation] = []
        for url in urls:
            product = await self.scrape(url, classify=classify, source_listing_url=source_listing_url)
            if on_result is not None:
                on_result(product)
            results.append(product)
        return results
