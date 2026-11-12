from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from scraper.extraction import extract_product
from scraper.promotions import MultibuyTier, parse_discount_label, parse_multibuy_tiers, resolve_day_month

OCT_20 = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


def test_parses_multibuy_tiers_with_nbsp_and_en_dash() -> None:
    texts = ["2,99\xa0€", "od 2\xa0ks", "–11 %", "2,69 €", "od 3 ks", "-20 %"]
    assert parse_multibuy_tiers(texts) == [
        MultibuyTier(min_qty=2, promo_price=Decimal("2.99"), discount_pct=11),
        MultibuyTier(min_qty=3, promo_price=Decimal("2.69"), discount_pct=20),
    ]


def test_multibuy_tier_without_quantity_is_dropped() -> None:
    assert parse_multibuy_tiers(["2,99 €", "–11 %"]) == []


@pytest.mark.parametrize(
    ("scraped_at", "expected"),
    [
        (OCT_20, date(2026, 10, 20)),
        (datetime(2026, 10, 1, tzinfo=timezone.utc), date(2026, 10, 20)),
        (datetime(2026, 10, 21, tzinfo=timezone.utc), date(2027, 10, 20)),
    ],
)
def test_resolve_day_month_uses_next_year_only_when_past(scraped_at: datetime, expected: date) -> None:
    assert resolve_day_month(20, 10, scraped_at) == expected


def test_discount_label_with_and_without_date() -> None:
    assert parse_discount_label("-54 % do 20. 10.", OCT_20).valid_until == date(2026, 10, 20)
    label = parse_discount_label("–30 %", OCT_20)
    assert (label.discount_pct, label.valid_until, label.date_unparsed) == (30, None, False)


def test_impossible_date_is_flagged_not_raised() -> None:
    label = parse_discount_label("-10 % do 31. 2.", OCT_20)
    assert label.valid_until is None
    assert label.date_unparsed is True


def test_discount_without_label_computes_percentage() -> None:
    html = """
    <div data-tid="product-detail__overlay_price">
      <section data-tid="pbox-price"><span>1,50</span> <s data-tid="product-box__crossed-price">2,00</s></section>
    </div>
    """
    product = extract_product(html, "https://www.kosik.sk/p1-x", scraped_at=OCT_20)
    assert [(p.type, p.promo_price, p.discount_pct, p.valid_until) for p in product.promotions] == [
        ("discount", Decimal("1.50"), 25, None)
    ]


def test_unparsable_shelf_life_is_flagged() -> None:
    html = '<p data-tid="product-detail__bestBefore_top"><span>Minimálna trvanlivosť: </span><span>2 mesiace</span></p>'
    product = extract_product(html, "https://www.kosik.sk/p1-x", scraped_at=OCT_20)
    assert product.min_shelf_life_days is None
    assert "unparsed_shelf_life" in product.extraction.warnings


def test_multibuy_outside_product_detail_is_ignored() -> None:
    html = """
    <section data-tid="similar-products">
      <button data-tid="cumulative-price-step"><span>2,99 €</span><span>od 2 ks</span><span>–11 %</span></button>
    </section>
    """
    product = extract_product(html, "https://www.kosik.sk/p1-x", scraped_at=OCT_20)
    assert product.promotions == []
