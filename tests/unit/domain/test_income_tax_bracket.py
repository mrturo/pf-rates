"""Tests for IncomeTaxBracket value object."""

from datetime import date
from decimal import Decimal

import pytest

from financial_data.domain.income_tax_bracket import IncomeTaxBracket


def test_income_tax_bracket_creation_valid() -> None:
    """Income tax bracket can be created with valid data."""
    bracket = IncomeTaxBracket(
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        lower_bound_utm=Decimal("13.5"),
        upper_bound_utm=Decimal("30.0"),
        marginal_rate=Decimal("0.04"),
        rebate_utm=Decimal("0.54"),
    )
    assert bracket.valid_from == date(2026, 1, 1)
    assert bracket.valid_to == date(2026, 12, 31)
    assert bracket.lower_bound_utm == Decimal("13.5")
    assert bracket.upper_bound_utm == Decimal("30.0")
    assert bracket.marginal_rate == Decimal("0.04")
    assert bracket.rebate_utm == Decimal("0.54")


def test_income_tax_bracket_creation_no_upper_bound() -> None:
    """Income tax bracket can have no upper bound (top bracket)."""
    bracket = IncomeTaxBracket(
        valid_from=date(2026, 1, 1),
        valid_to=None,
        lower_bound_utm=Decimal("120.0"),
        upper_bound_utm=None,
        marginal_rate=Decimal("0.35"),
        rebate_utm=Decimal("15.0"),
    )
    assert bracket.upper_bound_utm is None
    assert bracket.valid_to is None


def test_income_tax_bracket_rejects_negative_lower_bound() -> None:
    """Negative lower_bound_utm is rejected."""
    with pytest.raises(ValueError, match="lower_bound_utm must be >= 0"):
        IncomeTaxBracket(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            lower_bound_utm=Decimal("-1.0"),
            upper_bound_utm=Decimal("10.0"),
            marginal_rate=Decimal("0.04"),
            rebate_utm=Decimal("0.0"),
        )


def test_income_tax_bracket_rejects_upper_bound_equal_to_lower() -> None:
    """Upper bound equal to lower bound is rejected."""
    with pytest.raises(
        ValueError, match="upper_bound_utm .* must be greater than lower_bound_utm"
    ):
        IncomeTaxBracket(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            lower_bound_utm=Decimal("10.0"),
            upper_bound_utm=Decimal("10.0"),
            marginal_rate=Decimal("0.04"),
            rebate_utm=Decimal("0.0"),
        )


def test_income_tax_bracket_rejects_upper_bound_less_than_lower() -> None:
    """Upper bound less than lower bound is rejected."""
    with pytest.raises(
        ValueError, match="upper_bound_utm .* must be greater than lower_bound_utm"
    ):
        IncomeTaxBracket(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            lower_bound_utm=Decimal("20.0"),
            upper_bound_utm=Decimal("10.0"),
            marginal_rate=Decimal("0.04"),
            rebate_utm=Decimal("0.0"),
        )


def test_income_tax_bracket_rejects_marginal_rate_below_zero() -> None:
    """Marginal rate below 0 is rejected."""
    with pytest.raises(ValueError, match="marginal_rate must be in \\[0, 1\\]"):
        IncomeTaxBracket(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            lower_bound_utm=Decimal("10.0"),
            upper_bound_utm=Decimal("20.0"),
            marginal_rate=Decimal("-0.05"),
            rebate_utm=Decimal("0.0"),
        )


def test_income_tax_bracket_rejects_marginal_rate_above_one() -> None:
    """Marginal rate above 1 is rejected."""
    with pytest.raises(ValueError, match="marginal_rate must be in \\[0, 1\\]"):
        IncomeTaxBracket(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            lower_bound_utm=Decimal("10.0"),
            upper_bound_utm=Decimal("20.0"),
            marginal_rate=Decimal("1.5"),
            rebate_utm=Decimal("0.0"),
        )


def test_income_tax_bracket_accepts_marginal_rate_zero() -> None:
    """Marginal rate of 0 is valid (first bracket)."""
    bracket = IncomeTaxBracket(
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        lower_bound_utm=Decimal("0.0"),
        upper_bound_utm=Decimal("13.5"),
        marginal_rate=Decimal("0.0"),
        rebate_utm=Decimal("0.0"),
    )
    assert bracket.marginal_rate == Decimal("0.0")


def test_income_tax_bracket_accepts_marginal_rate_one() -> None:
    """Marginal rate of 1 (100%) is theoretically valid."""
    bracket = IncomeTaxBracket(
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        lower_bound_utm=Decimal("1000.0"),
        upper_bound_utm=None,
        marginal_rate=Decimal("1.0"),
        rebate_utm=Decimal("0.0"),
    )
    assert bracket.marginal_rate == Decimal("1.0")


def test_income_tax_bracket_rejects_negative_rebate() -> None:
    """Negative rebate_utm is rejected."""
    with pytest.raises(ValueError, match="rebate_utm must be >= 0"):
        IncomeTaxBracket(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            lower_bound_utm=Decimal("10.0"),
            upper_bound_utm=Decimal("20.0"),
            marginal_rate=Decimal("0.04"),
            rebate_utm=Decimal("-1.0"),
        )


def test_income_tax_bracket_is_frozen() -> None:
    """IncomeTaxBracket is immutable (frozen dataclass)."""
    bracket = IncomeTaxBracket(
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        lower_bound_utm=Decimal("10.0"),
        upper_bound_utm=Decimal("20.0"),
        marginal_rate=Decimal("0.04"),
        rebate_utm=Decimal("0.0"),
    )
    try:
        bracket.marginal_rate = Decimal("0.10")  # type: ignore
        assert False, "Should have raised FrozenInstanceError"
    except AttributeError:
        pass  # Expected
