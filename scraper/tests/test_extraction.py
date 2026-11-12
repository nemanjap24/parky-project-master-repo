from decimal import Decimal
from pathlib import Path

from scraper.extraction import extract_product


FIXTURE = Path(__file__).parents[1] / "fixtures" / "sample_kosik_product.html"


def test_extracts_product_fields() -> None:
    product = extract_product(FIXTURE.read_text(encoding="utf-8"), "https://www.kosik.sk/product/milk")
    assert product.raw_title == "K-Classic Mlieko plnotucne 1 l"
    assert product.price == 0.89
    assert product.regular_price == Decimal("1.09")
    assert product.is_discounted is True
    assert product.unit == "l"


def test_missing_values_are_none() -> None:
    product = extract_product("<html><h1 class='product-title'>Plain item</h1></html>", "https://www.kosik.sk/product/plain")
    assert product.price is None
    assert product.regular_price is None
    assert product.availability is None


def test_uses_rendered_data_testid_and_meta_title() -> None:
    html = """
    <meta property="og:title" content="Fallback title">
    <div data-testid="product-title">Rendered title</div>
    <span data-testid="product-price">2,49 €</span>
    """
    product = extract_product(html, "https://www.kosik.sk/product/rendered")
    assert product.raw_title == "Rendered title"
    assert product.price == 2.49


def test_unit_comes_from_price_per_unit_before_product_size() -> None:
    html = """
    <h1 data-tid="product-detail__product-name">Frozen fries</h1>
    <p data-tid="product-detail__product-weight">750 g</p>
    <section data-tid="pbox-price"><span>1,59</span></section>
    <s data-tid="product-box__crossed-price">2,89</s>
    <div data-tid="pbox-price-per-unit"><span>2,12</span><span>€/kg</span></div>
    """
    product = extract_product(html, "https://www.kosik.sk/product/fries")
    assert product.unit == "kg"


def test_page_without_json_ld_falls_back_to_html_with_warnings() -> None:
    product = extract_product(FIXTURE.read_text(encoding="utf-8"), "https://www.kosik.sk/p123-mlieko")
    assert product.name == "K-Classic Mlieko plnotucne 1 l"
    assert product.retailer_product_id == "123"
    assert product.shelf_price == Decimal("0.89")
    assert product.currency is None
    assert product.in_stock is None
    assert product.extraction.source == "html"
    assert product.extraction.warnings == ["missing_json_ld", "price_fallback_html"]


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


def test_json_ld_price_wins_and_conflict_is_flagged() -> None:
    html = """
    <script type="application/ld+json">
      {"@type": "Product", "sku": "5", "name": "Syr", "offers": {"price": "2.49", "priceCurrency": "EUR"}}
    </script>
    <div data-tid="product-detail__overlay_price"><section data-tid="pbox-price"><span>2,99</span></section></div>
    """
    product = extract_product(html, "https://www.kosik.sk/p5-syr")
    assert product.shelf_price == Decimal("2.49")
    assert product.extraction.source == "json-ld+html"
    assert product.extraction.warnings == ["price_source_conflict", "missing_breadcrumb"]


def test_scraped_at_can_be_injected() -> None:
    from datetime import datetime, timezone

    moment = datetime(2026, 11, 14, 8, 12, 44, tzinfo=timezone.utc)
    product = extract_product("<h1>X</h1>", "https://www.kosik.sk/p1-x", scraped_at=moment)
    assert product.scraped_at == moment
