"""Tests for ExchangeRate value object."""

from datetime import date
from decimal import Decimal

import pytest

from financial_data.domain.exchange_rate import ExchangeRate


def test_exchange_rate_creation_valid() -> None:
    """Exchange rate can be created with valid data."""
    rate = ExchangeRate(
        currency_code="USD",
        rate_date=date(2026, 7, 23),
        value_clp=Decimal("850.50"),
        source="banco_central",
    )
    assert rate.currency_code == "USD"
    assert rate.rate_date == date(2026, 7, 23)
    assert rate.value_clp == Decimal("850.50")
    assert rate.source == "banco_central"


def test_exchange_rate_creation_minimal() -> None:
    """Exchange rate can be created with minimal fields."""
    rate = ExchangeRate(
        currency_code="EUR",
        rate_date=date(2026, 7, 23),
        value_clp=Decimal("950.0"),
    )
    assert rate.currency_code == "EUR"
    assert rate.source == "manual"


def test_exchange_rate_rejects_zero_value() -> None:
    """Exchange rate with zero value is rejected."""
    with pytest.raises(ValueError, match="value_clp must be positive"):
        ExchangeRate(
            currency_code="USD",
            rate_date=date(2026, 7, 23),
            value_clp=Decimal("0"),
        )


def test_exchange_rate_rejects_negative_value() -> None:
    """Exchange rate with negative value is rejected."""
    with pytest.raises(ValueError, match="value_clp must be positive"):
        ExchangeRate(
            currency_code="USD",
            rate_date=date(2026, 7, 23),
            value_clp=Decimal("-100.5"),
        )


def test_exchange_rate_is_frozen() -> None:
    """ExchangeRate is immutable (frozen dataclass)."""
    rate = ExchangeRate(
        currency_code="USD",
        rate_date=date(2026, 7, 23),
        value_clp=Decimal("850.50"),
    )
    try:
        rate.value_clp = Decimal("900.0")  # type: ignore
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass  # Expected
