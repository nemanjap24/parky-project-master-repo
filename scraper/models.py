"""Typed scraper data models (output schema version 0.2).

One ``ProductObservation`` is one JSONL line: static product data together with
one price observation, so it can later be split into product and price-history
tables. Field meanings are documented in ``docs/output-format.md``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer

from qwen_classifier.models import Category

SCHEMA_VERSION = "0.2"
SCRAPER_VERSION = "0.2.0"

PackageUnit = Literal["g", "kg", "ml", "l", "ks"]
BaseUnit = Literal["kg", "l", "ks"]


def _to_cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Exact decimals in Python; JSON numbers in output. Money is rounded to cents.
Money = Annotated[
    Decimal,
    AfterValidator(_to_cents),
    PlainSerializer(float, return_type=float, when_used="json"),
]
def _quantity_json(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


# Package quantities: whole numbers stay integers in JSON (250, not 250.0).
Quantity = Annotated[Decimal, Field(gt=0), PlainSerializer(_quantity_json, return_type=int | float, when_used="json")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Package(_Strict):
    raw: str
    amount: Quantity
    unit: PackageUnit
    base_quantity: Quantity
    base_unit: BaseUnit


class UnitPrice(_Strict):
    value: Money | None = None
    per: BaseUnit | None = None
    computed: Money | None = None


class Promotion(_Strict):
    """A price condition shown next to the shelf price.

    ``discount``: crossed-out regular price, ``promo_price`` equals the shelf price.
    ``multibuy``: Multikup tier, price per piece when buying at least ``min_qty``.
    ``price_match``: "Dorovnaná cena" label, no price of its own.
    """

    type: Literal["discount", "multibuy", "price_match"]
    min_qty: int | None = Field(default=None, ge=1)
    promo_price: Money | None = None
    discount_pct: int | None = Field(default=None, ge=0, le=100)
    valid_until: date | None = None


class Classification(_Strict):
    category: Category
    subcategory: str | None = None
    confidence: float = Field(ge=0, le=1)
    model: str
    prompt_version: str
    classified_at: datetime


class Extraction(_Strict):
    """Where the record's data came from and what looked suspicious."""

    source: Literal["json-ld+html", "html"]
    scraper_version: str = SCRAPER_VERSION
    warnings: list[str] = Field(default_factory=list)


class ProductObservation(_Strict):
    schema_version: Literal["0.2"] = SCHEMA_VERSION
    run_id: str | None = None
    scraped_at: datetime
    retailer: Literal["kosik"] = "kosik"
    retailer_product_id: str | None = None
    url: str
    source_listing_url: str | None = None

    name: str | None = None
    brand: str | None = None
    package: Package | None = None
    retailer_category_id: str | None = None
    retailer_category_path: list[str] = Field(default_factory=list)
    country_of_origin: str | None = None
    min_shelf_life_days: int | None = Field(default=None, ge=0)

    currency: str | None = None
    shelf_price: Money | None = None
    regular_price: Money | None = None
    unit_price: UnitPrice | None = None
    promotions: list[Promotion] = Field(default_factory=list)
    in_stock: bool | None = None

    classification: Classification | None = None
    extraction: Extraction

    @property
    def needs_review(self) -> bool:
        return len(self.extraction.warnings) > 0
