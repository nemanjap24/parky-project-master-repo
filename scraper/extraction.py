"""Deterministic extraction of product fields from rendered HTML."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser

from .jsonld import parse_product_json_ld
from .models import Extraction, ScrapedProduct


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.current: list[str] = []
        self.classes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        self.classes.append(
            " ".join(
                [
                    tag,
                    attrs_dict.get("class", "") or "",
                    attrs_dict.get("id", "") or "",
                    attrs_dict.get("data-tid", "") or "",
                    attrs_dict.get("data-testid", "") or "",
                    attrs_dict.get("aria-label", "") or "",
                ]
            ).lower()
        )

    def handle_endtag(self, tag: str) -> None:
        if self.classes:
            self.classes.pop()

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        self.parts.append(text)
        self.current.append(" ".join(self.classes) + "\t" + text)


def _fields(html: str) -> list[tuple[str, str]]:
    parser = _TextParser()
    parser.feed(html)
    return [tuple(item.split("\t", 1)) for item in parser.current if "\t" in item]


def _meta(html: str, key: str) -> str | None:
    pattern = re.compile(
        rf"<meta[^>]+(?:property|name)=[\"'][^\"']*{re.escape(key)}[^\"']*[\"'][^>]+content=[\"']([^\"']+)",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    return " ".join(match.group(1).split()) if match else None


def _first_text(fields: list[tuple[str, str]], patterns: tuple[str, ...]) -> str | None:
    for context, text in fields:
        if any(pattern in context for pattern in patterns):
            return text
    return None


def _combined_text(fields: list[tuple[str, str]], patterns: tuple[str, ...]) -> str | None:
    values = [text for context, text in fields if any(pattern in context for pattern in patterns)]
    return " ".join(values) if values else None


def _scoped_text(fields: list[tuple[str, str]], scope: str, tid: str) -> str | None:
    """First text whose ancestors include the ``scope`` token and the exact ``tid`` token."""

    for context, text in fields:
        tokens = context.split()
        if scope in tokens and tid in tokens:
            return text
    return None


def _decimal_price(value: str | None) -> Decimal | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:[,.]\d{1,2})?", value.replace("\xa0", " "))
    return Decimal(match.group(0).replace(",", ".")) if match else None


def _price(value: str | None) -> float | None:
    amount = _decimal_price(value)
    return float(amount) if amount is not None else None


def _unit(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(kg|g|l|ml|ks)\b", value.lower())
    return match.group(1) if match else None


_OVERLAY_PRICE = "product-detail__overlay_price"
_URL_PRODUCT_ID = re.compile(r"/p(\d+)-")
# Generic HTML price hints. A bare "price" is deliberately absent: it also matches
# Multikup tiers ("cumulative-price-step"), which are not the shelf price.
_HTML_PRICE_PATTERNS = ("pbox-price", "sale-price", "current-price", "product-price")
_HTML_REGULAR_PRICE_PATTERNS = ("product-box__crossed-price", "regular-price", "old-price", "original-price")


def _html_shelf_price(fields: list[tuple[str, str]]) -> Decimal | None:
    scoped = _scoped_text(fields, _OVERLAY_PRICE, "pbox-price")
    if scoped is not None:
        return _decimal_price(scoped)
    candidates = [(context, text) for context, text in fields if "cumulative-price-step" not in context]
    return _decimal_price(_first_text(candidates, _HTML_PRICE_PATTERNS))


def _html_regular_price(fields: list[tuple[str, str]]) -> Decimal | None:
    scoped = _scoped_text(fields, _OVERLAY_PRICE, "product-box__crossed-price")
    if scoped is not None:
        return _decimal_price(scoped)
    return _decimal_price(_first_text(fields, _HTML_REGULAR_PRICE_PATTERNS))


def _html_title(page_content: str, fields: list[tuple[str, str]]) -> str | None:
    title = _first_text(
        fields,
        (
            "product-title",
            "product_name",
            "product-name",
            "producttitle",
            "product-detail__product-name",
        ),
    )
    title = title or _meta(page_content, "og:title")
    return title or next((text for context, text in fields if context.startswith("h1 ")), None)


def extract_product(page_content: str, url: str, scraped_at: datetime | None = None) -> ScrapedProduct:
    """Extract one product observation from a rendered Kosik product page.

    JSON-LD is the primary source for identity, price, currency, stock and
    category. HTML is used for fields JSON-LD does not carry and as a flagged
    fallback when JSON-LD is missing.
    """

    fields = _fields(page_content)
    json_ld = parse_product_json_ld(page_content)
    warnings: list[str] = []

    html_price = _html_shelf_price(fields)
    if json_ld is None:
        warnings.append("missing_json_ld")
    if json_ld is not None and json_ld.price is not None:
        shelf_price: Decimal | None = json_ld.price
        if html_price is not None and html_price != json_ld.price:
            warnings.append("price_source_conflict")
    else:
        shelf_price = html_price
        if html_price is not None:
            warnings.append("price_fallback_html")
    if json_ld is not None and not json_ld.category_path:
        warnings.append("missing_breadcrumb")

    name = (json_ld.name if json_ld else None) or _html_title(page_content, fields)
    url_id = _URL_PRODUCT_ID.search(url)
    product_id = (json_ld.sku if json_ld else None) or (url_id.group(1) if url_id else None)
    html_brand = _first_text(fields, ("product-detail__main-info__info_brand",))
    regular_price = _html_regular_price(fields)
    unit_price = _combined_text(
        fields,
        ("pbox-price-per-unit", "price-per-unit", "unit-price", "priceperunit"),
    )
    weight = _first_text(
        fields,
        ("product-detail__product-weight", "weight", "volume", "quantity", "size"),
    )
    availability = _first_text(
        fields,
        ("availability", "stock", "in-stock", "product-to-cart__to-cart"),
    )
    discounted = regular_price is not None and shelf_price is not None and regular_price > shelf_price
    return ScrapedProduct(
        retailer_product_id=product_id,
        url=url,
        scraped_at=scraped_at or datetime.now(timezone.utc),
        name=name,
        brand=(json_ld.brand if json_ld else None) or html_brand,
        retailer_category_id=json_ld.category_id if json_ld else None,
        retailer_category_path=json_ld.category_path if json_ld else [],
        currency=json_ld.currency if json_ld else None,
        shelf_price=shelf_price,
        regular_price=regular_price,
        in_stock=json_ld.in_stock if json_ld else None,
        extraction=Extraction(source="json-ld+html" if json_ld else "html", warnings=warnings),
        raw_title=name or "Unknown product",
        price=float(shelf_price) if shelf_price is not None else None,
        price_per_unit=_price(unit_price),
        unit=_unit(unit_price) or _unit(weight),
        weight_or_volume=weight,
        is_discounted=discounted,
        availability=availability,
    )

