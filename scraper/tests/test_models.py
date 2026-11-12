import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from scraper.models import Extraction, Package, ProductObservation, Promotion, UnitPrice

NOW = datetime(2026, 11, 14, 8, 12, 44, tzinfo=timezone.utc)


def _observation(**overrides: object) -> ProductObservation:
    data: dict[str, object] = {
        "url": "https://www.kosik.sk/p1-x",
        "scraped_at": NOW,
        "extraction": Extraction(source="json-ld+html"),
    }
    data.update(overrides)
    return ProductObservation(**data)


def test_defaults() -> None:
    product = _observation()
    assert product.schema_version == "0.2"
    assert product.retailer == "kosik"
    assert product.promotions == []
    assert product.classification is None
    assert product.extraction.scraper_version == "0.2.0"
    assert product.needs_review is False


def test_needs_review_follows_warnings() -> None:
    product = _observation(extraction=Extraction(source="html", warnings=["missing_json_ld"]))
    assert product.needs_review is True


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _observation(availability="Do košíka")


def test_unknown_retailer_and_units_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _observation(retailer="Kosik")
    with pytest.raises(ValidationError):
        Package(raw="1 bal", amount=Decimal(1), unit="bal", base_quantity=Decimal(1), base_unit="ks")


def test_money_is_rounded_to_cents_and_serialized_as_number() -> None:
    product = _observation(
        shelf_price=Decimal("3.385"),
        unit_price=UnitPrice(value=Decimal("13.56"), per="kg", computed=Decimal("13.5")),
        promotions=[Promotion(type="multibuy", min_qty=2, promo_price=Decimal("2.99"), discount_pct=11)],
        package=Package(raw="250 g", amount=Decimal(250), unit="g", base_quantity=Decimal("0.25"), base_unit="kg"),
    )
    assert product.shelf_price == Decimal("3.39")
    payload = json.loads(product.model_dump_json())
    assert payload["shelf_price"] == 3.39
    assert payload["unit_price"] == {"value": 13.56, "per": "kg", "computed": 13.5}
    assert payload["promotions"][0]["promo_price"] == 2.99
    assert payload["package"]["base_quantity"] == 0.25
    assert '"amount":250,' in product.model_dump_json()


def test_json_round_trip() -> None:
    product = _observation(
        shelf_price=Decimal("1.15"),
        promotions=[Promotion(type="discount", promo_price=Decimal("0.79"), discount_pct=54, valid_until=date(2026, 10, 20))],
    )
    restored = ProductObservation.model_validate_json(product.model_dump_json())
    assert restored == product


def test_invalid_promotion_values() -> None:
    with pytest.raises(ValidationError):
        Promotion(type="bogo")
    with pytest.raises(ValidationError):
        Promotion(type="multibuy", min_qty=0)
