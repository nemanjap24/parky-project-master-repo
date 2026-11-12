from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scraper.extraction import extract_product

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sample_kosik_product.html"


def test_page_without_json_ld_falls_back_to_html_with_warnings() -> None:
    product = extract_product(FIXTURE.read_text(encoding="utf-8"), "https://www.kosik.sk/p123-mlieko")
    assert product.name == "K-Classic Mlieko plnotucne 1 l"
    assert product.retailer_product_id == "123"
    assert product.shelf_price == Decimal("0.89")
    assert product.regular_price == Decimal("1.09")
    assert product.package is not None and product.package.base_unit == "l"
    assert product.unit_price is not None
    assert (product.unit_price.value, product.unit_price.per, product.unit_price.computed) == (
        Decimal("0.89"),
        "l",
        Decimal("0.89"),
    )
    assert [promotion.type for promotion in product.promotions] == ["discount"]
    assert product.currency is None
    assert product.in_stock is None
    assert product.extraction.source == "html"
    assert product.extraction.warnings == ["missing_json_ld", "price_fallback_html"]
    assert product.needs_review is True


def test_missing_values_are_none_and_flagged() -> None:
    product = extract_product("<html><h1 class='product-title'>Plain item</h1></html>", "https://www.kosik.sk/product/plain")
    assert product.name == "Plain item"
    assert product.retailer_product_id is None
    assert product.shelf_price is None
    assert product.regular_price is None
    assert product.package is None
    assert product.unit_price is None
    assert product.in_stock is None
    assert product.extraction.warnings == ["missing_json_ld", "missing_package", "missing_price"]


def test_uses_rendered_data_testid_and_meta_title() -> None:
    html = """
    <meta property="og:title" content="Fallback title">
    <div data-testid="product-title">Rendered title</div>
    <span data-testid="product-price">2,49 €</span>
    """
    product = extract_product(html, "https://www.kosik.sk/product/rendered")
    assert product.name == "Rendered title"
    assert product.shelf_price == Decimal("2.49")


def test_unit_price_unit_comes_from_price_per_unit_text() -> None:
    html = """
    <h1 data-tid="product-detail__product-name">Frozen fries</h1>
    <p data-tid="product-detail__product-weight">750 g</p>
    <section data-tid="pbox-price"><span>1,59</span></section>
    <s data-tid="product-box__crossed-price">2,89</s>
    <div data-tid="pbox-price-per-unit"><span>2,12</span><span>€/kg</span></div>
    """
    product = extract_product(html, "https://www.kosik.sk/product/fries")
    assert product.unit_price is not None
    assert product.unit_price.per == "kg"
    assert product.unit_price.computed == Decimal("2.12")


def test_multibuy_tier_is_not_taken_as_html_price() -> None:
    html = """
    <div data-tid="product-detail__info">
      <h1 data-tid="product-detail__product-name">Parky</h1>
      <button data-tid="cumulative-price-step"><span>2,99 €</span><span>od 2 ks</span></button>
      <div data-tid="product-detail__overlay_price">
        <section data-tid="pbox-price"><span>3,39</span></section>
      </div>
    </div>
    """
    product = extract_product(html, "https://www.kosik.sk/p7004-parky")
    assert product.shelf_price == Decimal("3.39")


def _json_ld_page(price: str, body: str) -> str:
    return f"""
    <script type="application/ld+json">
      {{"@type": "Product", "sku": "5", "name": "Syr", "offers": {{"price": "{price}", "priceCurrency": "EUR"}}}}
    </script>
    <div data-tid="product-detail__info"><p data-tid="product-detail__product-weight">200 g</p></div>
    {body}
    """


def test_json_ld_price_wins_and_conflict_is_flagged() -> None:
    html = _json_ld_page(
        "2.49",
        '<div data-tid="product-detail__overlay_price"><section data-tid="pbox-price"><span>2,99</span></section></div>',
    )
    product = extract_product(html, "https://www.kosik.sk/p5-syr")
    assert product.shelf_price == Decimal("2.49")
    assert product.extraction.source == "json-ld+html"
    assert product.extraction.warnings == ["price_source_conflict", "missing_breadcrumb"]


def test_unit_price_mismatch_is_flagged() -> None:
    html = _json_ld_page(
        "2.00",
        '<div data-tid="product-detail__overlay_price"><div data-tid="pbox-price-per-unit">'
        "<span>11,00</span><span>€/kg</span></div></div>",
    )
    product = extract_product(html, "https://www.kosik.sk/p5-syr")
    assert product.unit_price is not None
    assert product.unit_price.computed == Decimal("10.00")
    assert "unit_price_mismatch" in product.extraction.warnings


def test_unit_price_within_tolerance_is_not_flagged() -> None:
    html = _json_ld_page(
        "2.00",
        '<div data-tid="product-detail__overlay_price"><div data-tid="pbox-price-per-unit">'
        "<span>10,15</span><span>€/kg</span></div></div>",
    )
    product = extract_product(html, "https://www.kosik.sk/p5-syr")
    assert "unit_price_mismatch" not in product.extraction.warnings


def test_unparsed_package_is_flagged() -> None:
    html = '<div data-tid="product-detail__info"><p data-tid="product-detail__product-weight">cca 1 balenie</p></div>'
    product = extract_product(html, "https://www.kosik.sk/p1-x")
    assert product.package is None
    assert "unparsed_package" in product.extraction.warnings


def test_scraped_at_can_be_injected() -> None:
    moment = datetime(2026, 11, 14, 8, 12, 44, tzinfo=timezone.utc)
    product = extract_product("<h1>X</h1>", "https://www.kosik.sk/p1-x", scraped_at=moment)
    assert product.scraped_at == moment
