"""Tests for the RefreshIncomeTaxBrackets use case."""

from datetime import date
from decimal import Decimal

import pytest

from financial_data.application.dto import (
    IncomeTaxBracketWriteDTO,
    RefreshIncomeTaxBracketsCommandDTO,
    RefreshIncomeTaxBracketsResultDTO,
)
from financial_data.application.use_cases.refresh_income_tax_brackets import (
    RefreshIncomeTaxBrackets,
)


_JAN_BRACKET = IncomeTaxBracketWriteDTO(
    valid_from=date(2026, 1, 1),
    valid_to=date(2026, 1, 31),
    lower_bound_utm=Decimal("0.0000"),
    upper_bound_utm=Decimal("13.5000"),
    marginal_rate=Decimal("0.000000"),
    rebate_utm=Decimal("0.0000"),
)
_FEB_BRACKET = IncomeTaxBracketWriteDTO(
    valid_from=date(2026, 2, 1),
    valid_to=date(2026, 2, 28),
    lower_bound_utm=Decimal("0.0000"),
    upper_bound_utm=Decimal("13.5000"),
    marginal_rate=Decimal("0.000000"),
    rebate_utm=Decimal("0.0000"),
)


class StubReferenceDataRepository:
    """Test double for ReferenceDataRepository."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self.upserted: list[IncomeTaxBracketWriteDTO] = []

    async def list_currencies(self) -> list[object]:
        """List currencies."""
        raise AssertionError("not used")

    async def list_income_tax_brackets(self, year: int | None = None) -> list[object]:
        """List income tax brackets."""
        raise AssertionError("not used")

    async def get_income_tax_bracket(
        self, payment_date: object, taxable_base_utm: object
    ) -> None:
        """Get income tax bracket."""
        raise AssertionError("not used")

    async def upsert_income_tax_brackets(
        self, brackets: list[IncomeTaxBracketWriteDTO]
    ) -> int:
        """Handle upsert income tax brackets."""
        self.upserted = brackets
        return len(brackets)


class StubProvider:
    """Test double for IncomeTaxBracketProvider."""

    def __init__(self, brackets: list[IncomeTaxBracketWriteDTO]) -> None:
        """Initialize the instance."""
        self._brackets = brackets

    async def fetch_income_tax_brackets(
        self, year: int
    ) -> list[IncomeTaxBracketWriteDTO]:
        """Handle fetch income tax brackets."""
        return self._brackets


async def test_refresh_income_tax_brackets_upserts_and_counts_months() -> None:
    """Fetched brackets are persisted and the correct month count is returned."""
    repository = StubReferenceDataRepository()
    use_case = RefreshIncomeTaxBrackets(
        repository, StubProvider([_JAN_BRACKET, _FEB_BRACKET])
    )

    result = await use_case.execute(RefreshIncomeTaxBracketsCommandDTO(year=2026))

    assert result == RefreshIncomeTaxBracketsResultDTO(
        year=2026, refreshed_months=2, upserted_brackets=2
    )
    assert repository.upserted == [_JAN_BRACKET, _FEB_BRACKET]


async def test_refresh_income_tax_brackets_raises_when_provider_returns_nothing() -> (
    None
):
    """A dependency error is raised if the provider returns no brackets."""
    with pytest.raises(ValueError, match="No official income tax brackets were found"):
        await RefreshIncomeTaxBrackets(
            StubReferenceDataRepository(), StubProvider([])
        ).execute(RefreshIncomeTaxBracketsCommandDTO(year=2026))
