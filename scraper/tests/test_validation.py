from decimal import Decimal

from scraper.package import parse_package
from scraper.models import UnitPrice
from scraper.validation import compute_unit_price, observation_warnings

PACK_250_G = parse_package("250 g")
PACK_5_KG = parse_package("5 kg")


def test_compute_unit_price_rounds_half_up() -> None:
    assert compute_unit_price(Decimal("12.49"), PACK_5_KG) == Decimal("2.50")
    assert compute_unit_price(Decimal("3.39"), PACK_250_G) == Decimal("13.56")
    assert compute_unit_price(None, PACK_250_G) is None
    assert compute_unit_price(Decimal("1"), None) is None


def _warnings(**overrides: object) -> list[str]:
    data: dict[str, object] = {
        "shelf_price": Decimal("3.39"),
        "regular_price": None,
        "package": PACK_250_G,
        "unit_price": UnitPrice(value=Decimal("13.56"), per="kg", computed=Decimal("13.56")),
    }
    data.update(overrides)
    return observation_warnings(**data)  # type: ignore[arg-type]


def test_consistent_observation_has_no_warnings() -> None:
    assert _warnings() == []


def test_price_checks() -> None:
    assert _warnings(shelf_price=None, unit_price=None) == ["missing_price"]
    assert "non_positive_price" in _warnings(shelf_price=Decimal("0"), unit_price=None)
    assert _warnings(regular_price=Decimal("3.39")) == ["regular_price_not_higher"]
    assert _warnings(regular_price=Decimal("3.99")) == []


def test_unit_price_tolerance_is_two_percent() -> None:
    within = UnitPrice(value=Decimal("13.83"), per="kg", computed=Decimal("13.56"))
    outside = UnitPrice(value=Decimal("13.84"), per="kg", computed=Decimal("13.56"))
    assert _warnings(unit_price=within) == []
    assert _warnings(unit_price=outside) == ["unit_price_mismatch"]


def test_unit_price_in_different_unit_is_flagged_instead_of_compared() -> None:
    other_unit = UnitPrice(value=Decimal("3.39"), per="ks", computed=Decimal("13.56"))
    assert _warnings(unit_price=other_unit) == ["unit_price_unit_mismatch"]
