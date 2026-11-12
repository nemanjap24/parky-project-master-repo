from decimal import Decimal

import pytest

from scraper.package import parse_package


@pytest.mark.parametrize(
    ("raw", "amount", "unit", "base_quantity", "base_unit"),
    [
        ("250 g", "250", "g", "0.25", "kg"),
        ("0,5 kg", "0.5", "kg", "0.5", "kg"),
        ("5 kg", "5", "kg", "5", "kg"),
        ("750 ml", "750", "ml", "0.75", "l"),
        ("1,5 l", "1.5", "l", "1.5", "l"),
        ("1 L", "1", "l", "1", "l"),
        ("10 ks", "10", "ks", "10", "ks"),
        ("4 x 100 g", "400", "g", "0.4", "kg"),
        ("6x0,5 l", "3", "l", "3", "l"),
        ("2 × 125\xa0g", "250", "g", "0.25", "kg"),
    ],
)
def test_parses_package_labels(raw: str, amount: str, unit: str, base_quantity: str, base_unit: str) -> None:
    package = parse_package(raw)
    assert package is not None
    assert package.amount == Decimal(amount)
    assert package.unit == unit
    assert package.base_quantity == Decimal(base_quantity)
    assert package.base_unit == base_unit


def test_raw_label_is_whitespace_normalized() -> None:
    package = parse_package("  250\xa0g ")
    assert package is not None
    assert package.raw == "250 g"


def test_amounts_have_no_exponent_notation() -> None:
    package = parse_package("250 g")
    assert package is not None
    assert str(package.amount) == "250"
    assert str(package.base_quantity) == "0.25"


@pytest.mark.parametrize("raw", [None, "", "cca 1 balenie", "0 g", "250 dkg", "1-2 kg"])
def test_unparseable_labels_return_none(raw: str | None) -> None:
    assert parse_package(raw) is None
