"""Parsing of schema.org JSON-LD embedded in rendered Kosik product pages.

Kosik publishes a ``@graph`` with separate ``Product``, ``Offer`` and
``BreadcrumbList`` nodes. ``Product.offers`` usually only references the offer by
``@id``, so nodes are indexed by ``@id`` and references are resolved.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_SCRIPT = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_CATEGORY_ID = re.compile(r"/(c\d+)(?:-|$|/|\?)")
_PRODUCT_URL = re.compile(r"/p\d+(?:-|$|/|\?)")


class JsonLdProduct(BaseModel):
    """Product data found in the page's JSON-LD."""

    model_config = ConfigDict(extra="forbid")

    sku: str | None = None
    name: str | None = None
    brand: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    availability: str | None = None
    category_path: list[str] = Field(default_factory=list)
    category_urls: list[str] = Field(default_factory=list)

    @property
    def in_stock(self) -> bool | None:
        if not self.availability:
            return None
        state = self.availability.rstrip("/").rsplit("/", 1)[-1]
        if state in {"InStock", "LimitedAvailability", "OnlineOnly", "InStoreOnly"}:
            return True
        if state in {"OutOfStock", "SoldOut", "Discontinued"}:
            return False
        return None

    @property
    def category_ids(self) -> list[str | None]:
        """Category id of each breadcrumb entry (aligned with ``category_path``)."""

        ids: list[str | None] = []
        for url in self.category_urls:
            match = _CATEGORY_ID.search(url)
            ids.append(match.group(1) if match else None)
        return ids

    @property
    def category_id(self) -> str | None:
        return self.category_ids[-1] if self.category_ids else None


def _nodes(html: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for match in _SCRIPT.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                nodes.extend(node for node in graph if isinstance(node, dict))
            else:
                nodes.append(item)
    return nodes


def _has_type(node: dict[str, Any], name: str) -> bool:
    node_type = node.get("@type")
    return node_type == name or (isinstance(node_type, list) and name in node_type)


def _resolve(value: Any, index: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, dict) and "@id" in value and len(value) == 1:
        return index.get(value["@id"], value)
    return value


def _text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = " ".join(str(value).split())
        return text or None
    return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except InvalidOperation:
        return None


def _offer(product: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    offers = _resolve(product.get("offers"), index)
    if isinstance(offers, list):
        offers = next((_resolve(item, index) for item in offers if isinstance(item, dict)), None)
    if isinstance(offers, dict) and _has_type(offers, "AggregateOffer"):
        offers = {**offers, "price": offers.get("price", offers.get("lowPrice"))}
    return offers if isinstance(offers, dict) else {}


def _breadcrumb(nodes: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    crumbs = next((node for node in nodes if _has_type(node, "BreadcrumbList")), None)
    if crumbs is None:
        return [], []
    elements = [item for item in crumbs.get("itemListElement", []) if isinstance(item, dict)]
    elements.sort(key=lambda item: item.get("position") if isinstance(item.get("position"), int) else 0)
    names: list[str] = []
    urls: list[str] = []
    for element in elements:
        item = element.get("item")
        url = item if isinstance(item, str) else item.get("@id") if isinstance(item, dict) else None
        name = _text(element.get("name")) or _text(item if isinstance(item, dict) else None)
        if not name or (url and _PRODUCT_URL.search(url)):
            continue
        names.append(name)
        urls.append(url or "")
    return names, urls


def parse_product_json_ld(html: str) -> JsonLdProduct | None:
    """Return product data from JSON-LD, or ``None`` when no ``Product`` node exists.

    Malformed JSON-LD blocks are skipped rather than raising, because the HTML
    fallback can still produce a (flagged) record.
    """

    nodes = _nodes(html)
    index = {node["@id"]: node for node in nodes if isinstance(node.get("@id"), str)}
    product = next((node for node in nodes if _has_type(node, "Product")), None)
    if product is None:
        return None
    offer = _offer(product, index)
    path, urls = _breadcrumb(nodes)
    return JsonLdProduct(
        sku=_text(product.get("sku")),
        name=_text(product.get("name")),
        brand=_text(_resolve(product.get("brand"), index)),
        price=_decimal(offer.get("price")),
        currency=_text(offer.get("priceCurrency")),
        availability=_text(offer.get("availability")),
        category_path=path,
        category_urls=urls,
    )
