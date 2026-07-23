"""Tests for EconomicIndex value object."""

from decimal import Decimal

import pytest

from financial_data.domain.economic_index import EconomicIndex


def test_economic_index_creation_valid() -> None:
    """Economic index can be created with valid data."""
    index = EconomicIndex(
        code="IPC",
        period_year=2026,
        period_month=7,
        index_value=Decimal("115.42"),
        monthly_change=Decimal("0.5"),
        yearly_change=Decimal("3.2"),
        base_period="DIC-2018",
        source="INE",
    )
    assert index.code == "IPC"
    assert index.period_year == 2026
    assert index.period_month == 7
    assert index.index_value == Decimal("115.42")
    assert index.monthly_change == Decimal("0.5")
    assert index.yearly_change == Decimal("3.2")
    assert index.base_period == "DIC-2018"
    assert index.source == "INE"


def test_economic_index_creation_minimal() -> None:
    """Economic index can be created with minimal required fields."""
    index = EconomicIndex(
        code="IPC",
        period_year=2026,
        period_month=1,
        index_value=Decimal("100.0"),
    )
    assert index.code == "IPC"
    assert index.monthly_change is None
    assert index.yearly_change is None
    assert index.base_period == "DIC-2018"
    assert index.source == "manual"


def test_economic_index_rejects_invalid_month_low() -> None:
    """Period month below 1 is rejected."""
    with pytest.raises(ValueError, match="period_month must be between 1 and 12"):
        EconomicIndex(
            code="IPC",
            period_year=2026,
            period_month=0,
            index_value=Decimal("100.0"),
        )


def test_economic_index_rejects_invalid_month_high() -> None:
    """Period month above 12 is rejected."""
    with pytest.raises(ValueError, match="period_month must be between 1 and 12"):
        EconomicIndex(
            code="IPC",
            period_year=2026,
            period_month=13,
            index_value=Decimal("100.0"),
        )


def test_economic_index_rejects_zero_value() -> None:
    """Index value of zero is rejected."""
    with pytest.raises(ValueError, match="index_value must be positive"):
        EconomicIndex(
            code="IPC",
            period_year=2026,
            period_month=7,
            index_value=Decimal("0"),
        )


def test_economic_index_rejects_negative_value() -> None:
    """Negative index value is rejected."""
    with pytest.raises(ValueError, match="index_value must be positive"):
        EconomicIndex(
            code="IPC",
            period_year=2026,
            period_month=7,
            index_value=Decimal("-10.5"),
        )


def test_economic_index_is_frozen() -> None:
    """EconomicIndex is immutable (frozen dataclass)."""
    index = EconomicIndex(
        code="IPC",
        period_year=2026,
        period_month=7,
        index_value=Decimal("100.0"),
    )
    try:
        index.index_value = Decimal("200.0")  # type: ignore
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass  # Expected
