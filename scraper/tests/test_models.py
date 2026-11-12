from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from scraper.models import ScrapedProduct


def test_valid_product_model() -> None:
    product = ScrapedProduct(url="https://www.kosik.sk/product/x", scraped_at=datetime.now(timezone.utc), raw_title="Milk", price=1.2)
    assert product.retailer == "kosik"


def test_invalid_price_type() -> None:
    with pytest.raises(ValidationError):
        ScrapedProduct(url="https://www.kosik.sk/product/x", scraped_at=datetime.now(timezone.utc), raw_title="Milk", price="1.2")


def test_invalid_unit() -> None:
    with pytest.raises(ValidationError):
        ScrapedProduct(url="https://www.kosik.sk/product/x", scraped_at=datetime.now(timezone.utc), raw_title="Milk", unit="piece")


def test_default_values() -> None:
    product = ScrapedProduct(url="https://www.kosik.sk/product/x", scraped_at=datetime.now(timezone.utc), raw_title="Milk")
    assert product.is_discounted is False
    assert product.category is None
    assert product.confidence is None
    assert product.needs_review is False
