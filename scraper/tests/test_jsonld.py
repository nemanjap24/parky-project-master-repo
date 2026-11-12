import json
from decimal import Decimal

from scraper.jsonld import parse_product_json_ld


def _page(*blocks: object) -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{block if isinstance(block, str) else json.dumps(block)}</script>'
        for block in blocks
    )
    return f"<html><head>{scripts}</head><body></body></html>"


GRAPH = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "Organization", "@id": "https://www.kosik.sk/#organization"},
        {
            "@type": "Product",
            "@id": "https://www.kosik.sk/p1-x#product",
            "sku": 1,
            "name": "  Test   párky ",
            "brand": {"@type": "Brand", "name": "Značka"},
            "offers": {"@id": "https://www.kosik.sk/p1-x#offer"},
        },
        {
            "@type": "Offer",
            "@id": "https://www.kosik.sk/p1-x#offer",
            "price": "3.39",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 2, "name": "Párky", "item": "https://www.kosik.sk/c3350-parky"},
                {"@type": "ListItem", "position": 1, "name": "Údeniny", "item": "https://www.kosik.sk/c3338-udeniny"},
            ],
        },
    ],
}


def test_resolves_offer_reference_and_breadcrumb_order() -> None:
    product = parse_product_json_ld(_page(GRAPH))
    assert product is not None
    assert product.sku == "1"
    assert product.name == "Test párky"
    assert product.brand == "Značka"
    assert product.price == Decimal("3.39")
    assert product.currency == "EUR"
    assert product.in_stock is True
    assert product.category_path == ["Údeniny", "Párky"]
    assert product.category_id == "c3350"


def test_inline_offer_list_and_out_of_stock() -> None:
    page = _page(
        {
            "@type": "Product",
            "name": "Mlieko",
            "brand": "K-Classic",
            "offers": [{"@type": "Offer", "price": 0.89, "availability": "http://schema.org/OutOfStock"}],
        }
    )
    product = parse_product_json_ld(page)
    assert product is not None
    assert product.brand == "K-Classic"
    assert product.price == Decimal("0.89")
    assert product.in_stock is False
    assert product.category_path == []
    assert product.category_id is None


def test_breadcrumb_drops_trailing_product_entry() -> None:
    graph = json.loads(json.dumps(GRAPH))
    graph["@graph"][3]["itemListElement"].append(
        {"@type": "ListItem", "position": 3, "name": "Test párky", "item": "https://www.kosik.sk/p1-x"}
    )
    product = parse_product_json_ld(_page(graph))
    assert product is not None
    assert product.category_path == ["Údeniny", "Párky"]
    assert product.category_id == "c3350"


def test_malformed_block_is_skipped() -> None:
    product = parse_product_json_ld(_page("{not json", GRAPH))
    assert product is not None
    assert product.sku == "1"


def test_missing_product_node_returns_none() -> None:
    assert parse_product_json_ld(_page({"@type": "Organization", "name": "Košík"})) is None
    assert parse_product_json_ld("<html></html>") is None


def test_unknown_availability_is_none() -> None:
    page = _page({"@type": "Product", "name": "X", "offers": {"price": "1", "availability": "https://schema.org/PreOrder"}})
    product = parse_product_json_ld(page)
    assert product is not None
    assert product.in_stock is None
