"""Port definition for market-data persistence."""

from datetime import date
from decimal import Decimal
from typing import Protocol

from financial_data.application.dto import (
    EconomicIndexDTO,
    ExchangeRateDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)


class MarketDataRepository(Protocol):
    """Persistence port for historical exchange rates and economic indices."""

    async def list_exchange_rates(
        self, currency_code: str | None
    ) -> list[ExchangeRateDTO]:
        """List stored exchange rates, optionally filtered by currency code."""
        ...

    async def list_economic_indices(self, code: str | None) -> list[EconomicIndexDTO]:
        """List stored economic indices, optionally filtered by code."""
        ...

    async def get_exchange_rate_value(self, code: str, on: date) -> Decimal | None:
        """Return the CLP value for a currency on the given date, or None."""
        ...

    async def list_exchange_rate_dates(
        self, code: str, start: date, end: date
    ) -> list[date]:
        """List stored exchange-rate dates for a currency within [start, end]."""
        ...

    async def get_economic_index_value(
        self, code: str, year: int, month: int
    ) -> Decimal | None:
        """Return the index value for the given code and period, or None."""
        ...

    async def list_economic_index_periods(
        self, code: str, ranges: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """Return (year, month) pairs from *ranges* that exist in the DB."""
        ...

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Upsert exchange rates and/or economic indices from the command."""
        ...
