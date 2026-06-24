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

    async def get_latest_exchange_rate_value_before(
        self, code: str, before: date, on_or_after: date | None = None
    ) -> Decimal | None:
        """Return the CLP value for the most recent rate strictly before *before*.

        When *on_or_after* is given the search is restricted to that window,
        so callers can enforce a maximum lookback horizon.
        """
        ...

    async def list_exchange_rate_dates(
        self, code: str, start: date, end: date
    ) -> list[date]:
        """List stored exchange-rate dates for a currency within [start, end]."""
        ...

    async def list_unconfirmed_rate_dates(
        self, code: str, start: date, end: date
    ) -> list[date]:
        """Return dates where the rate was fetched on or before its rate_date.

        A rate is unconfirmed when created_at (Chile time) <= rate_date — this
        covers both same-day fetches (value may be preliminary) and pre-publication
        fetches of future values (value may still be updated before the date arrives).
        Such rates are re-fetched on subsequent syncs until the fetch date is strictly
        after the rate date, at which point the value is considered final.
        """
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
