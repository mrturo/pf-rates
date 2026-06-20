"""Port definitions for market-data providers."""

from datetime import date
from decimal import Decimal
from typing import Protocol

from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ExchangeRateWriteDTO,
    IncomeTaxBracketWriteDTO,
)


class FxRateProvider(Protocol):
    """Provide fx rate provider."""

    async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
        """Handle fetch rate."""
        ...

    async def fetch_rate_entry(
        self, currency_code: str, on: date
    ) -> ExchangeRateWriteDTO | None:
        """Handle fetch rate entry."""
        ...

    async def fetch_rate_entries(
        self, currency_code: str, requested_dates: list[date]
    ) -> list[ExchangeRateWriteDTO]:
        """Handle fetch rate entries."""
        ...


class EconomicIndexProvider(Protocol):
    """Provide economic index provider."""

    async def fetch_index(
        self, code: str, period_year: int, period_month: int
    ) -> EconomicIndexWriteDTO | None:
        """Handle fetch index."""
        ...

    async def fetch_indices(
        self, code: str, requested_periods: list[tuple[int, int]]
    ) -> list[EconomicIndexWriteDTO]:
        """Handle fetch indices."""
        ...


class IncomeTaxBracketProvider(Protocol):
    """Provide income tax bracket provider."""

    async def fetch_income_tax_brackets(
        self, year: int
    ) -> list[IncomeTaxBracketWriteDTO]:
        """Handle fetch income tax brackets."""
        ...
