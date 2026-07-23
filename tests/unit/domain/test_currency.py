"""Tests for Currency value object."""

from financial_data.domain.currency import Currency


def test_currency_creation_fiat() -> None:
    """Fiat currency can be created with valid attributes."""
    currency = Currency(
        code="USD",
        name="US Dollar",
        is_fiat=True,
        unit_kind="daily",
    )
    assert currency.code == "USD"
    assert currency.name == "US Dollar"
    assert currency.is_fiat is True
    assert currency.unit_kind == "daily"


def test_currency_creation_non_fiat() -> None:
    """Non-fiat currency can be created."""
    currency = Currency(
        code="UF",
        name="Unidad de Fomento",
        is_fiat=False,
        unit_kind="daily",
    )
    assert currency.code == "UF"
    assert currency.name == "Unidad de Fomento"
    assert currency.is_fiat is False


def test_currency_is_frozen() -> None:
    """Currency is immutable (frozen dataclass)."""
    currency = Currency(
        code="EUR",
        name="Euro",
        is_fiat=True,
        unit_kind="daily",
    )
    try:
        currency.code = "GBP"  # type: ignore
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass  # Expected
