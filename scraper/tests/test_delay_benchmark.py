from datetime import datetime, timezone

import pytest

from scraper.crawler import CrawlError
from scraper.delay_benchmark import (
    _empty_page_reason,
    _scrape_failure_type,
    delay_values,
    validate_page_counts,
)
from scraper.extraction import extract_product
from scraper.discovery import CategoryListing, DiscoveryManifest


def test_delay_sweep_runs_from_half_to_five_seconds() -> None:
    assert delay_values() == [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]


def test_page_counts_are_unique_and_sorted() -> None:
    assert validate_page_counts([30, 15, 30], available_urls=30) == [15, 30]


@pytest.mark.parametrize("counts", [[], [0], [31]])
def test_invalid_page_counts_are_rejected(counts: list[int]) -> None:
    with pytest.raises(ValueError):
        validate_page_counts(counts, available_urls=30)


def test_page_counts_cannot_exceed_manifest_urls() -> None:
    with pytest.raises(ValueError, match="contains 15 unique product URLs"):
        validate_page_counts([30], available_urls=15)


def test_empty_rendered_page_is_detected_from_missing_name_and_price() -> None:
    product = extract_product(
        "<html><body></body></html>",
        "https://www.kosik.sk/p123-example",
    )

    assert _empty_page_reason(product) == "No product name or shelf price was extracted"


def test_incomplete_page_with_product_name_is_not_marked_empty() -> None:
    product = extract_product(
        '<html><body><h1 class="product-title">Example product</h1></body></html>',
        "https://www.kosik.sk/p123-example",
    )

    assert _empty_page_reason(product) is None


def test_empty_rendered_html_failure_is_distinguished_from_scrape_error() -> None:
    assert _scrape_failure_type(CrawlError("Rendered page was empty: https://www.kosik.sk/p123-example")) == (
        "empty_page"
    )
    assert _scrape_failure_type(CrawlError("Timed out while loading a page")) == "scrape_error"


def test_discovery_manifest_can_contain_30_non_live_product_urls() -> None:
    urls = [f"https://example.invalid/p{index:08d}-dummy-product" for index in range(1, 31)]
    manifest = DiscoveryManifest(
        discovered_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
        listings=[
            CategoryListing(
                category_id="c9999",
                category_name="Dummy test category",
                url="https://example.invalid/c9999-dummy-category",
                product_urls=urls,
                load_more_clicks=0,
                complete=True,
            )
        ],
    )

    assert manifest.product_count == 30
    assert all(url.startswith("https://example.invalid/") for url in urls)
