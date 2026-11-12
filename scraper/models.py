"""Typed scraper data models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StrictFloat

SCRAPER_VERSION = "0.2.0"

# Prices are exact decimals in Python and plain JSON numbers in output.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class Extraction(BaseModel):
    """Where the record's data came from and what looked suspicious."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["json-ld+html", "html"]
    scraper_version: str = SCRAPER_VERSION
    warnings: list[str] = Field(default_factory=list)


class ScrapedProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retailer: Literal["kosik"] = "kosik"
    retailer_product_id: str | None = None
    url: str
    scraped_at: datetime

    name: str | None = None
    brand: str | None = None
    retailer_category_id: str | None = None
    retailer_category_path: list[str] = Field(default_factory=list)

    currency: str | None = None
    shelf_price: Money | None = None
    regular_price: Money | None = None
    in_stock: bool | None = None

    extraction: Extraction = Field(default_factory=lambda: Extraction(source="html"))

    # v1 fields, kept until the model is replaced in step 4 of docs/scraper-model-v2.md.
    raw_title: str
    price: StrictFloat | None = None
    price_per_unit: StrictFloat | None = None
    unit: Literal["kg", "g", "l", "ml", "ks"] | None = None
    weight_or_volume: str | None = None
    is_discounted: bool = False
    availability: str | None = None
    category: str | None = None
    subcategory: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    needs_review: bool = False
