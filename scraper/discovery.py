"""Category whitelist and discovery manifest for the Kosik crawler.

The whitelist (``config/kosik_categories.json``) says which Kosik categories are
collected and on which weekend day. Discovery turns it into a manifest: for each
category the listing URL and the product URLs found on it. The manifest is saved
before scraping so an interrupted run can be resumed without discovering again.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_CATEGORIES_CONFIG = Path("config/kosik_categories.json")
MANIFEST_SCHEMA_VERSION = "0.1"

ScrapeDay = Literal["fri", "sat", "sun"]

_CATEGORY_ID = re.compile(r"/(c\d+)(?:-|/|$)")


def category_id_from_url(url: str | None) -> str | None:
    """``https://www.kosik.sk/c3365-slaniny`` → ``c3365``."""

    if not url:
        return None
    match = _CATEGORY_ID.search(url.split("?", 1)[0])
    return match.group(1) if match else None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryEntry(_Strict):
    """One whitelisted category. ``id`` is the stable Kosik id; the slug in URLs may change."""

    id: str = Field(pattern=r"^c\d+$")
    name: str
    day: ScrapeDay | None = None


class CategoryWhitelist(_Strict):
    retailer: Literal["kosik"] = "kosik"
    categories: list[CategoryEntry] = Field(min_length=1)

    @field_validator("categories")
    @classmethod
    def _unique_ids(cls, categories: list[CategoryEntry]) -> list[CategoryEntry]:
        ids = [category.id for category in categories]
        duplicates = sorted({category_id for category_id in ids if ids.count(category_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate category ids: {', '.join(duplicates)}")
        return categories

    def for_day(self, day: ScrapeDay | None) -> list[CategoryEntry]:
        """All categories, or only those planned for ``day``."""

        return list(self.categories) if day is None else [c for c in self.categories if c.day == day]


def load_category_whitelist(path: Path = DEFAULT_CATEGORIES_CONFIG) -> CategoryWhitelist:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read category whitelist {path}: {exc}") from exc
    try:
        return CategoryWhitelist.model_validate_json(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid category whitelist {path}: {exc}") from exc


class CategoryListing(_Strict):
    """Product URLs found on one whitelisted category page.

    ``complete`` is ``False`` when the "Načítať ďalšie" button was still present
    after the click limit, or when the page did not report its loading state;
    the product list may then be truncated.
    """

    category_id: str
    category_name: str
    url: str
    product_urls: list[str]
    load_more_clicks: int | None = None
    complete: bool


class DiscoveryManifest(_Strict):
    schema_version: Literal["0.1"] = MANIFEST_SCHEMA_VERSION
    retailer: Literal["kosik"] = "kosik"
    run_id: str | None = None
    discovered_at: datetime
    listings: list[CategoryListing]
    missing_category_ids: list[str] = Field(default_factory=list)

    @property
    def product_count(self) -> int:
        return len({url for listing in self.listings for url in listing.product_urls})


def write_manifest(manifest: DiscoveryManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> DiscoveryManifest:
    try:
        return DiscoveryManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read discovery manifest {path}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"Invalid discovery manifest {path}: {exc}") from exc
