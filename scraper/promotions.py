"""Parsing of Kosik promotion texts (Multikup tiers, discount labels, dates).

These helpers work on already extracted visible text so they stay independent of
page markup and easy to test.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

_PRICE = re.compile(r"^(\d+[,.]\d{1,2})\s*€$")
_MIN_QTY = re.compile(r"^od\s*(\d+)\s*ks$", re.IGNORECASE)
_PERCENT = re.compile(r"[-–]\s*(\d+)\s*%")
_DAY_MONTH = re.compile(r"\bdo\s*(\d{1,2})\.\s*(\d{1,2})\.?", re.IGNORECASE)


@dataclass(frozen=True)
class MultibuyTier:
    min_qty: int
    promo_price: Decimal
    discount_pct: int | None


@dataclass(frozen=True)
class DiscountLabel:
    discount_pct: int | None
    valid_until: date | None
    date_unparsed: bool = False


def parse_multibuy_tiers(texts: Iterable[str]) -> list[MultibuyTier]:
    """Parse the text sequence of Multikup buttons: ``2,99 €``, ``od 2 ks``, ``–11 %``, ..."""

    tiers: list[MultibuyTier] = []
    price: Decimal | None = None
    min_qty: int | None = None
    pct: int | None = None

    def flush() -> None:
        if price is not None and min_qty is not None:
            tiers.append(MultibuyTier(min_qty=min_qty, promo_price=price, discount_pct=pct))

    for raw in texts:
        text = " ".join(raw.split())
        if match := _PRICE.match(text):
            flush()
            price, min_qty, pct = Decimal(match.group(1).replace(",", ".")), None, None
        elif match := _MIN_QTY.match(text):
            min_qty = int(match.group(1))
        elif match := _PERCENT.search(text):
            pct = int(match.group(1))
    flush()
    return tiers


def resolve_day_month(day: int, month: int, scraped_at: datetime) -> date:
    """Attach a year to a ``DD. MM.`` date: the scrape year, or the next one if already past."""

    reference = scraped_at.date()
    candidate = date(reference.year, month, day)
    return candidate if candidate >= reference else date(reference.year + 1, month, day)


def parse_discount_label(text: str, scraped_at: datetime) -> DiscountLabel:
    """Parse a label such as ``-54 % do 20. 10.``."""

    pct_match = _PERCENT.search(text)
    date_match = _DAY_MONTH.search(text)
    valid_until: date | None = None
    unparsed = False
    if date_match:
        try:
            valid_until = resolve_day_month(int(date_match.group(1)), int(date_match.group(2)), scraped_at)
        except ValueError:
            unparsed = True
    return DiscountLabel(
        discount_pct=int(pct_match.group(1)) if pct_match else None,
        valid_until=valid_until,
        date_unparsed=unparsed,
    )
