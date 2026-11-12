"""Consistency checks on an extracted observation.

Checks never raise; each problem becomes a warning code in
``extraction.warnings`` so that the record is kept but marked for review.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .models import Package, UnitPrice

UNIT_PRICE_TOLERANCE = Decimal("0.02")
CENT = Decimal("0.01")


def compute_unit_price(shelf_price: Decimal | None, package: Package | None) -> Decimal | None:
    """``shelf_price / base_quantity`` rounded half-up to cents."""

    if shelf_price is None or package is None or package.base_quantity <= 0:
        return None
    return (shelf_price / package.base_quantity).quantize(CENT, rounding=ROUND_HALF_UP)


def observation_warnings(
    *,
    shelf_price: Decimal | None,
    regular_price: Decimal | None,
    package: Package | None,
    unit_price: UnitPrice | None,
) -> list[str]:
    warnings: list[str] = []
    if shelf_price is None:
        warnings.append("missing_price")
    elif shelf_price <= 0:
        warnings.append("non_positive_price")
    if regular_price is not None and shelf_price is not None and regular_price <= shelf_price:
        warnings.append("regular_price_not_higher")
    if unit_price is not None and unit_price.value is not None and package is not None:
        if unit_price.per is not None and unit_price.per != package.base_unit:
            warnings.append("unit_price_unit_mismatch")
        elif unit_price.computed:
            deviation = abs(unit_price.value - unit_price.computed) / unit_price.computed
            if deviation > UNIT_PRICE_TOLERANCE:
                warnings.append("unit_price_mismatch")
    return warnings
