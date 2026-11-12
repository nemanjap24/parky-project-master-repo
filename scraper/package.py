"""Normalization of package sizes such as ``250 g``, ``1,5 l`` or ``4 x 100 g``."""

from __future__ import annotations

import re
from decimal import Decimal

from .models import BaseUnit, Package, PackageUnit

_PACKAGE = re.compile(
    r"^(?:(?P<count>\d+)\s*[x×]\s*)?(?P<amount>\d+(?:[,.]\d+)?)\s*(?P<unit>kg|g|ml|l|ks)\.?$",
    re.IGNORECASE,
)
_TO_BASE: dict[PackageUnit, tuple[BaseUnit, Decimal]] = {
    "g": ("kg", Decimal("0.001")),
    "kg": ("kg", Decimal("1")),
    "ml": ("l", Decimal("0.001")),
    "l": ("l", Decimal("1")),
    "ks": ("ks", Decimal("1")),
}


def _plain(value: Decimal) -> Decimal:
    """Drop trailing zeros without switching to exponent notation (``250``, not ``2.5E+2``)."""

    normalized = value.normalize()
    return normalized.quantize(Decimal(1)) if normalized == normalized.to_integral() else normalized


def parse_package(raw: str | None) -> Package | None:
    """Parse a Kosik package label; ``None`` when the label is missing or not understood.

    For multipacks (``4 x 100 g``) ``amount`` is the total (``400 g``); ``raw`` keeps
    the original label.
    """

    if raw is None:
        return None
    text = " ".join(raw.replace("\xa0", " ").split())
    match = _PACKAGE.match(text)
    if match is None:
        return None
    unit: PackageUnit = match.group("unit").lower()  # type: ignore[assignment]
    amount = Decimal(match.group("amount").replace(",", "."))
    if match.group("count"):
        amount *= int(match.group("count"))
    if amount <= 0:
        return None
    base_unit, factor = _TO_BASE[unit]
    return Package(
        raw=text,
        amount=_plain(amount),
        unit=unit,
        base_quantity=_plain(amount * factor),
        base_unit=base_unit,
    )
