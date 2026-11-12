"""Regression tests for scraper model v2 against real rendered Kosik pages.

The fixtures are full rendered pages captured by ``KosikCrawler``. Each test pins
``scraped_at`` to the day the page was rendered so that promotion dates such as
``do 20. 10.`` resolve to a stable ISO date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scraper.extraction import extract_product

FIXTURES = Path(__file__).parents[1] / "fixtures"

SCRAPED_2026_10_20 = datetime(2026, 10, 20, 0, 47, tzinfo=timezone.utc)
SCRAPED_2026_10_31 = datetime(2026, 10, 31, 19, 27, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Expected:
    fixture: str
    url: str
    scraped_at: datetime
    product_id: str
    name: str
    brand: str | None
    shelf_price: str
    regular_price: str | None
    package_raw: str
    package_amount: str
    package_unit: str
    base_quantity: str
    unit_price: str
    unit_price_computed: str
    category_id: str
    category_path: tuple[str, ...]
    country_of_origin: str
    min_shelf_life_days: int | None
    promotion_types: tuple[str, ...]


CASES = [
    Expected(
        fixture="kosik_nord_svit_parky.html",
        url="https://www.kosik.sk/p7004-nord-svit-zlate-parky-93-maesa",
        scraped_at=SCRAPED_2026_10_31,
        product_id="7004",
        name="Nord Svit Zlaté párky (93% mäsa)",
        brand="Nord Svit",
        shelf_price="3.39",
        regular_price=None,
        package_raw="250 g",
        package_amount="250",
        package_unit="g",
        base_quantity="0.25",
        unit_price="13.56",
        unit_price_computed="13.56",
        category_id="c3350",
        category_path=("Údeniny a lahôdky", "Párky, klobásy, špekáčiky", "Párky"),
        country_of_origin="Slovensko",
        min_shelf_life_days=5,
        promotion_types=("multibuy", "multibuy"),
    ),
    Expected(
        fixture="kosik_tauris_parky.html",
        url="https://www.kosik.sk/p6902-tauris-zipser-parky-71-maesa",
        scraped_at=SCRAPED_2026_10_20,
        product_id="6902",
        name="Tauris Zipser párky (71% mäsa)",
        brand="Tauris",
        shelf_price="3.19",
        regular_price=None,
        package_raw="165 g",
        package_amount="165",
        package_unit="g",
        base_quantity="0.165",
        unit_price="19.33",
        unit_price_computed="19.33",
        category_id="c3350",
        category_path=("Údeniny a lahôdky", "Párky, klobásy, špekáčiky", "Párky"),
        country_of_origin="Slovensko",
        min_shelf_life_days=5,
        promotion_types=("multibuy",),
    ),
    Expected(
        fixture="kosik_citrony.html",
        url="https://www.kosik.sk/p39112-citrony",
        scraped_at=SCRAPED_2026_10_20,
        product_id="39112",
        name="Citróny",
        brand=None,
        shelf_price="0.79",
        regular_price="1.75",
        package_raw="500 g",
        package_amount="500",
        package_unit="g",
        base_quantity="0.5",
        unit_price="1.58",
        unit_price_computed="1.58",
        category_id="c2970",
        category_path=("Ovocie a zelenina", "Ovocie", "Citrusy", "Citróny"),
        country_of_origin="Španielsko",
        min_shelf_life_days=None,
        promotion_types=("discount",),
    ),
    Expected(
        fixture="kosik_fine_life_slanina.html",
        url="https://www.kosik.sk/p7224-fine-life-anglicka-slanina-platky-94-maeso",
        scraped_at=SCRAPED_2026_10_31,
        product_id="7224",
        name="Fine Life Anglická slanina plátky (94% mäso)",
        brand="Fine Life",
        shelf_price="1.15",
        regular_price=None,
        package_raw="100 g",
        package_amount="100",
        package_unit="g",
        base_quantity="0.1",
        unit_price="11.50",
        unit_price_computed="11.50",
        category_id="c3366",
        category_path=("Údeniny a lahôdky", "Slaniny", "Slanina"),
        country_of_origin="Európska únia",
        min_shelf_life_days=7,
        promotion_types=("price_match",),
    ),
    Expected(
        fixture="kosik_metro_chef_pomarance.html",
        url="https://www.kosik.sk/p24154-metro-chef-pomarance-dzusove",
        scraped_at=SCRAPED_2026_10_31,
        product_id="24154",
        name="Metro Chef Pomaranče džúsové",
        brand="Metro Chef",
        shelf_price="12.49",
        regular_price=None,
        package_raw="5 kg",
        package_amount="5",
        package_unit="kg",
        base_quantity="5",
        unit_price="2.50",
        unit_price_computed="2.50",
        category_id="c2969",
        category_path=("Ovocie a zelenina", "Ovocie", "Citrusy", "Pomaranče"),
        country_of_origin="Španielsko",
        min_shelf_life_days=None,
        promotion_types=(),
    ),
    Expected(
        fixture="kosik_mccain_golden_longs.html",
        url="https://www.kosik.sk/p1952-mccain-golden-longs-hranolky",
        scraped_at=SCRAPED_2026_10_20,
        product_id="1952",
        name="McCain Golden Longs hranolky",
        brand="McCain",
        shelf_price="1.59",
        regular_price="2.89",
        package_raw="750 g",
        package_amount="750",
        package_unit="g",
        base_quantity="0.75",
        unit_price="2.12",
        unit_price_computed="2.12",
        category_id="c3782",
        category_path=("Mrazené", "Zemiakové a cibuľové produkty", "Hranolčeky a vlnky", "Extra dlhé"),
        country_of_origin="Poľsko",
        min_shelf_life_days=31,
        promotion_types=("discount",),
    ),
]


def _extract(case: Expected, scraped_at: datetime | None = None):
    html = (FIXTURES / case.fixture).read_text(encoding="utf-8")
    return extract_product(html, case.url, scraped_at=scraped_at or case.scraped_at)


def _case(fixture: str) -> Expected:
    return next(case for case in CASES if case.fixture == fixture)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_identity_and_category_come_from_json_ld(case: Expected) -> None:
    product = _extract(case)
    assert product.retailer == "kosik"
    assert product.retailer_product_id == case.product_id
    assert product.url == case.url
    assert product.scraped_at == case.scraped_at
    assert product.name == case.name
    assert product.brand == case.brand
    assert product.retailer_category_id == case.category_id
    assert product.retailer_category_path == list(case.category_path)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_prices_and_stock(case: Expected) -> None:
    product = _extract(case)
    assert product.currency == "EUR"
    assert product.shelf_price == Decimal(case.shelf_price)
    expected_regular = Decimal(case.regular_price) if case.regular_price else None
    assert product.regular_price == expected_regular
    assert product.in_stock is True


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_package_and_unit_price(case: Expected) -> None:
    product = _extract(case)
    assert product.package.raw == case.package_raw
    assert product.package.amount == Decimal(case.package_amount)
    assert product.package.unit == case.package_unit
    assert product.package.base_quantity == Decimal(case.base_quantity)
    assert product.package.base_unit == ("kg" if case.package_unit in {"g", "kg"} else case.package_unit)
    assert product.unit_price.value == Decimal(case.unit_price)
    assert product.unit_price.per == "kg"
    assert product.unit_price.computed == Decimal(case.unit_price_computed)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_additional_product_details(case: Expected) -> None:
    product = _extract(case)
    assert product.country_of_origin == case.country_of_origin
    assert product.min_shelf_life_days == case.min_shelf_life_days
    assert tuple(promotion.type for promotion in product.promotions) == case.promotion_types


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.fixture)
def test_clean_pages_produce_no_warnings(case: Expected) -> None:
    product = _extract(case)
    assert product.extraction.source == "json-ld+html"
    assert product.extraction.warnings == []
    assert product.needs_review is False


def test_nord_svit_multibuy_does_not_replace_shelf_price() -> None:
    product = _extract(_case("kosik_nord_svit_parky.html"))
    assert product.shelf_price == Decimal("3.39")
    tiers = [(p.type, p.min_qty, p.promo_price, p.discount_pct, p.valid_until) for p in product.promotions]
    assert tiers == [
        ("multibuy", 2, Decimal("2.99"), 11, None),
        ("multibuy", 3, Decimal("2.69"), 20, None),
    ]


def test_tauris_multibuy_does_not_replace_shelf_price() -> None:
    product = _extract(_case("kosik_tauris_parky.html"))
    assert product.shelf_price == Decimal("3.19")
    tiers = [(p.type, p.min_qty, p.promo_price, p.discount_pct, p.valid_until) for p in product.promotions]
    assert tiers == [("multibuy", 2, Decimal("2.59"), 18, None)]


def test_citrony_discount_with_end_date() -> None:
    product = _extract(_case("kosik_citrony.html"))
    assert product.regular_price == Decimal("1.75")
    promotion = product.promotions[0]
    assert promotion.type == "discount"
    assert promotion.min_qty is None
    assert promotion.promo_price == Decimal("0.79")
    assert promotion.discount_pct == 54
    assert promotion.valid_until == date(2026, 10, 20)


def test_mccain_discount_with_end_date() -> None:
    product = _extract(_case("kosik_mccain_golden_longs.html"))
    promotion = product.promotions[0]
    assert promotion.type == "discount"
    assert promotion.promo_price == Decimal("1.59")
    assert promotion.discount_pct == 44
    assert promotion.valid_until == date(2026, 10, 20)


def test_discount_end_date_in_the_past_rolls_over_to_next_year() -> None:
    late_december = datetime(2026, 12, 30, 9, 0, tzinfo=timezone.utc)
    product = _extract(_case("kosik_citrony.html"), scraped_at=late_december)
    assert product.promotions[0].valid_until == date(2027, 10, 20)


def test_slanina_price_match_is_a_promotion_not_a_discount() -> None:
    product = _extract(_case("kosik_fine_life_slanina.html"))
    assert product.regular_price is None
    assert [promotion.type for promotion in product.promotions] == ["price_match"]


def test_availability_is_stock_state_not_button_text() -> None:
    product = _extract(_case("kosik_citrony.html"))
    assert product.in_stock is True
    assert not hasattr(product, "availability")
