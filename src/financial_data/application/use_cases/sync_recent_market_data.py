"""Use case for syncing recent market data history."""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from financial_data.application.dto import (
    MarketDataSyncRequestDTO,
    RefreshRatesCommandDTO,
    SyncRecentMarketDataResultDTO,
)
from financial_data.application.ports.market_data_repository import MarketDataRepository
from financial_data.application.ports.rate_provider import (
    EconomicIndexProvider,
    FxRateProvider,
    IncomeTaxBracketProvider,
)
from financial_data.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from financial_data.shared.constants import (
    DAILY_MARKET_RATE_CODES,
    FORWARD_DAILY_RATE_CODES,
    MONTHLY_ECONOMIC_INDEX_CODES,
    MONTHLY_MARKET_RATE_CODES,
)

_LOOKBACK_DAYS = 365
_LOOKBACK_MONTHS = 12
# Forward window for currencies that publish future values (e.g. UF).
_FORWARD_DAYS = 35


@dataclass(slots=True)
class SyncRecentMarketData:
    """Sync missing recent market data entries using provider-backed fetches."""

    repository: MarketDataRepository
    fx_provider: FxRateProvider
    economic_index_provider: EconomicIndexProvider
    reference_repository: ReferenceDataRepository
    bracket_provider: IncomeTaxBracketProvider
    today_provider: Callable[[], date] = date.today

    async def execute(
        self,
        lookback_days: int | None = None,
        forward_days: int | None = None,
    ) -> SyncRecentMarketDataResultDTO:
        """Handle execute.

        Args:
            lookback_days: Rolling lookback window in days. Defaults to
                _LOOKBACK_DAYS (365).
            forward_days: Forward window for currencies that publish future
                values (e.g. UF). Defaults to _FORWARD_DAYS (35).
        """
        today = self.today_provider()
        actual_lookback = lookback_days if lookback_days is not None else _LOOKBACK_DAYS
        actual_forward = forward_days if forward_days is not None else _FORWARD_DAYS
        daily_dates = self._build_daily_dates(today, actual_lookback)
        monthly_dates = self._build_monthly_dates(today)
        forward_dates = self._build_forward_dates(today, actual_forward)

        missing_exchange_rate_requests = await self._collect_missing_exchange_rates(
            daily_dates, monthly_dates, forward_dates
        )
        missing_economic_index_requests = await self._collect_missing_economic_indices(
            monthly_dates
        )
        rates_result = await self.execute_request(
            MarketDataSyncRequestDTO(
                exchange_rate_dates=missing_exchange_rate_requests,
                economic_index_periods=missing_economic_index_requests,
            )
        )
        years = {d.year for d in monthly_dates}
        upserted_brackets = await self._sync_income_tax_brackets(years)
        return dataclasses.replace(rates_result, upserted_brackets=upserted_brackets)

    async def execute_request(
        self, request: MarketDataSyncRequestDTO
    ) -> SyncRecentMarketDataResultDTO:
        """Synchronize the explicitly requested market-data gaps."""
        requested_exchange_rates = sum(
            len(rate_dates) for rate_dates in request.exchange_rate_dates.values()
        )
        requested_economic_indices = sum(
            len(periods) for periods in request.economic_index_periods.values()
        )

        upserted_exchange_rates = await self._sync_exchange_rates(
            request.exchange_rate_dates
        )
        upserted_economic_indices = await self._sync_economic_indices(
            request.economic_index_periods
        )

        return SyncRecentMarketDataResultDTO(
            requested_exchange_rates=requested_exchange_rates,
            requested_economic_indices=requested_economic_indices,
            upserted_exchange_rates=upserted_exchange_rates,
            upserted_economic_indices=upserted_economic_indices,
        )

    async def execute_request_and_collect_remaining(
        self, request: MarketDataSyncRequestDTO
    ) -> tuple[SyncRecentMarketDataResultDTO, MarketDataSyncRequestDTO | None]:
        """Synchronize a request and return any market-data gaps that remain."""
        result = await self.execute_request(request)
        remaining_request = await self.collect_remaining_request(request)
        return result, remaining_request

    async def collect_remaining_request(
        self, request: MarketDataSyncRequestDTO
    ) -> MarketDataSyncRequestDTO | None:
        """Return any requested market-data entries that are still missing."""
        remaining_exchange_rates = await self._collect_remaining_exchange_rates(
            request.exchange_rate_dates
        )
        remaining_economic_indices = await self._collect_remaining_economic_indices(
            request.economic_index_periods
        )
        if not remaining_exchange_rates and not remaining_economic_indices:
            return None
        return MarketDataSyncRequestDTO(
            exchange_rate_dates=remaining_exchange_rates,
            economic_index_periods=remaining_economic_indices,
        )

    async def _collect_missing_exchange_rates(
        self,
        daily_dates: list[date],
        monthly_dates: list[date],
        forward_dates: list[date],
    ) -> dict[str, list[date]]:
        """Collect missing exchange-rate requests.

        Daily rates fetched on the same calendar day as their rate_date are treated
        as missing so they are re-fetched — the published value may still be
        preliminary on that day.  Monthly rates are excluded from this logic as they
        are finalised on publication and do not change intraday.

        Currencies in FORWARD_DAILY_RATE_CODES also request forward_dates so that
        pre-published future values (e.g. UF) are stored as they become available.
        """
        missing_requests: dict[str, list[date]] = {}

        for currency_code in DAILY_MARKET_RATE_CODES:
            requested = (
                daily_dates + forward_dates
                if currency_code in FORWARD_DAILY_RATE_CODES
                else daily_dates
            )
            existing_dates = set(
                await self.repository.list_exchange_rate_dates(
                    currency_code, requested[0], requested[-1]
                )
            )
            same_day_dates = set(
                await self.repository.list_unconfirmed_rate_dates(
                    currency_code, requested[0], requested[-1]
                )
            )
            stable_dates = existing_dates - same_day_dates
            missing_requests[currency_code] = [
                rate_date for rate_date in requested if rate_date not in stable_dates
            ]

        for currency_code in MONTHLY_MARKET_RATE_CODES:
            existing_dates = set(
                await self.repository.list_exchange_rate_dates(
                    currency_code, monthly_dates[0], monthly_dates[-1]
                )
            )
            missing_requests[currency_code] = [
                rate_date
                for rate_date in monthly_dates
                if rate_date not in existing_dates
            ]

        return missing_requests

    async def _collect_missing_economic_indices(
        self, monthly_dates: list[date]
    ) -> dict[str, list[tuple[int, int]]]:
        """Collect missing economic-index requests."""
        missing_requests: dict[str, list[tuple[int, int]]] = {}
        all_periods = [(d.year, d.month) for d in monthly_dates]

        for code in MONTHLY_ECONOMIC_INDEX_CODES:
            existing_periods = set(
                await self.repository.list_economic_index_periods(code, all_periods)
            )
            missing_requests[code] = [
                period for period in all_periods if period not in existing_periods
            ]

        return missing_requests

    async def _sync_exchange_rates(
        self, requests_by_code: dict[str, list[date]]
    ) -> int:
        """Fetch and persist exchange-rate entries grouped by code."""
        upserted_exchange_rates = 0
        for currency_code, requested_dates in requests_by_code.items():
            if not requested_dates:
                continue
            exchange_rates = await self.fx_provider.fetch_rate_entries(
                currency_code, requested_dates
            )
            if not exchange_rates:
                continue
            refresh_result = await self.repository.refresh_rates(
                RefreshRatesCommandDTO(exchange_rates=exchange_rates)
            )
            upserted_exchange_rates += refresh_result.upserted_exchange_rates
        return upserted_exchange_rates

    async def _collect_remaining_exchange_rates(
        self, requests_by_code: dict[str, list[date]]
    ) -> dict[str, list[date]]:
        """Return requested exchange-rate dates that remain unavailable."""
        remaining_requests: dict[str, list[date]] = {}
        for currency_code, requested_dates in requests_by_code.items():
            if not requested_dates:
                continue
            existing_dates = set(
                await self.repository.list_exchange_rate_dates(
                    currency_code, requested_dates[0], requested_dates[-1]
                )
            )
            missing_dates = [
                requested_date
                for requested_date in requested_dates
                if requested_date not in existing_dates
            ]
            if missing_dates:
                remaining_requests[currency_code] = missing_dates
        return remaining_requests

    async def _sync_economic_indices(
        self, requests_by_code: dict[str, list[tuple[int, int]]]
    ) -> int:
        """Fetch and persist economic-index entries grouped by code."""
        upserted_economic_indices = 0
        for code, requested_periods in requests_by_code.items():
            if not requested_periods:
                continue
            economic_indices = await self.economic_index_provider.fetch_indices(
                code, requested_periods
            )
            if not economic_indices:
                continue
            refresh_result = await self.repository.refresh_rates(
                RefreshRatesCommandDTO(economic_indices=economic_indices)
            )
            upserted_economic_indices += refresh_result.upserted_economic_indices
        return upserted_economic_indices

    async def _collect_remaining_economic_indices(
        self, requests_by_code: dict[str, list[tuple[int, int]]]
    ) -> dict[str, list[tuple[int, int]]]:
        """Return requested economic-index periods that remain unavailable."""
        remaining_requests: dict[str, list[tuple[int, int]]] = {}
        for code, requested_periods in requests_by_code.items():
            if not requested_periods:
                continue
            existing_periods = set(
                await self.repository.list_economic_index_periods(
                    code, requested_periods
                )
            )
            missing_periods = [
                requested_period
                for requested_period in requested_periods
                if requested_period not in existing_periods
            ]
            if missing_periods:
                remaining_requests[code] = missing_periods
        return remaining_requests

    async def _sync_income_tax_brackets(self, years: set[int]) -> int:
        """Fetch and persist income tax brackets for years not yet in the DB."""
        upserted = 0
        for year in sorted(years):
            existing = await self.reference_repository.list_income_tax_brackets(year)
            if existing:
                continue
            brackets = await self.bracket_provider.fetch_income_tax_brackets(year)
            if not brackets:
                continue
            upserted += await self.reference_repository.upsert_income_tax_brackets(
                brackets
            )
        return upserted

    def _build_daily_dates(
        self, today: date, lookback_days: int = _LOOKBACK_DAYS
    ) -> list[date]:
        """Build daily dates for the rolling lookback window."""
        start_date = today - timedelta(days=lookback_days - 1)
        return [start_date + timedelta(days=offset) for offset in range(lookback_days)]

    def _build_forward_dates(
        self, today: date, forward_days: int = _FORWARD_DAYS
    ) -> list[date]:
        """Build future dates for currencies that publish values in advance."""
        return [today + timedelta(days=i) for i in range(1, forward_days + 1)]

    def _build_monthly_dates(self, today: date) -> list[date]:
        """Build monthly dates for the rolling twelve-month window."""
        month_cursor = date(today.year, today.month, 1)
        monthly_dates: list[date] = []
        for _ in range(_LOOKBACK_MONTHS):
            monthly_dates.append(month_cursor)
            month_cursor = self._previous_month(month_cursor)
        monthly_dates.reverse()
        return monthly_dates

    def _previous_month(self, month_date: date) -> date:
        """Return the first day of the previous month."""
        if month_date.month == 1:
            return date(month_date.year - 1, 12, 1)
        return date(month_date.year, month_date.month - 1, 1)
