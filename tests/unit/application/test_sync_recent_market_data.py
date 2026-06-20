"""Tests for the SyncRecentMarketData use case."""

from datetime import date, timedelta
from decimal import Decimal

from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ExchangeRateWriteDTO,
    MarketDataSyncRequestDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
    SyncRecentMarketDataResultDTO,
)
from financial_data.application.use_cases.sync_recent_market_data import (
    SyncRecentMarketData,
)


class StubMarketDataRepository:
    """Test double for MarketDataRepository with controllable responses."""

    def __init__(
        self,
        existing_dates: dict[str, list[date]] | None = None,
        existing_periods: dict[str, list[tuple[int, int]]] | None = None,
    ) -> None:
        """Initialize the instance."""
        self._existing_dates = existing_dates or {}
        self._existing_periods = existing_periods or {}
        self.refreshed: list[RefreshRatesCommandDTO] = []

    async def list_exchange_rate_dates(
        self, currency_code: str, start: date, end: date
    ) -> list[date]:
        """List exchange rate dates."""
        return self._existing_dates.get(currency_code, [])

    async def list_economic_index_periods(
        self, code: str, ranges: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """List economic index periods that exist from the requested ones."""
        existing = set(self._existing_periods.get(code, []))
        return [pair for pair in ranges if pair in existing]

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Capture refresh commands and return counts."""
        self.refreshed.append(command)
        return RefreshRatesResultDTO(
            upserted_exchange_rates=len(command.exchange_rates),
            upserted_economic_indices=len(command.economic_indices),
        )

    async def list_exchange_rates(self, currency_code: object = None) -> list[object]:
        """List exchange rates."""
        raise AssertionError("not used")

    async def list_economic_indices(self, code: object = None) -> list[object]:
        """List economic indices."""
        raise AssertionError("not used")

    async def get_exchange_rate_value(self, code: object, on: object) -> None:
        """Get exchange rate value."""
        raise AssertionError("not used")

    async def get_economic_index_value(
        self, code: object, year: object, month: object
    ) -> None:
        """Get economic index value."""
        raise AssertionError("not used")


class StubFxProvider:
    """Test double for FxRateProvider that returns one entry per requested date."""

    async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
        """Handle fetch rate."""
        return Decimal("1000")

    async def fetch_rate_entry(
        self, currency_code: str, on: date
    ) -> ExchangeRateWriteDTO | None:
        """Handle fetch rate entry."""
        return ExchangeRateWriteDTO(
            currency_code=currency_code, rate_date=on, value_clp=Decimal("1000")
        )

    async def fetch_rate_entries(
        self, currency_code: str, requested_dates: list[date]
    ) -> list[ExchangeRateWriteDTO]:
        """Handle fetch rate entries."""
        return [
            ExchangeRateWriteDTO(
                currency_code=currency_code, rate_date=d, value_clp=Decimal("1000")
            )
            for d in requested_dates
        ]


class StubIndexProvider:
    """Test double for EconomicIndexProvider that returns one entry per period."""

    async def fetch_index(
        self, code: str, period_year: int, period_month: int
    ) -> EconomicIndexWriteDTO | None:
        """Handle fetch index."""
        return EconomicIndexWriteDTO(
            code=code,
            period_year=period_year,
            period_month=period_month,
            index_value=Decimal("112"),
        )

    async def fetch_indices(
        self, code: str, requested_periods: list[tuple[int, int]]
    ) -> list[EconomicIndexWriteDTO]:
        """Handle fetch indices."""
        return [
            EconomicIndexWriteDTO(
                code=code,
                period_year=y,
                period_month=m,
                index_value=Decimal("112"),
            )
            for y, m in requested_periods
        ]


class EmptyFxProvider:
    """Test double for FxRateProvider that returns no entries."""

    async def fetch_rate_entries(
        self, currency_code: str, requested_dates: list[date]
    ) -> list[ExchangeRateWriteDTO]:
        """Handle fetch rate entries."""
        return []


class EmptyIndexProvider:
    """Test double for EconomicIndexProvider that returns no entries."""

    async def fetch_indices(
        self, code: str, requested_periods: list[tuple[int, int]]
    ) -> list[EconomicIndexWriteDTO]:
        """Handle fetch indices."""
        return []


async def test_execute_syncs_missing_entries() -> None:
    """execute() fetches and persists rates that are absent from the DB."""
    today = date(2026, 1, 15)
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    assert isinstance(result, SyncRecentMarketDataResultDTO)
    assert result.upserted_exchange_rates > 0
    assert result.upserted_economic_indices > 0
    assert len(repository.refreshed) > 0


async def test_execute_skips_already_existing_entries() -> None:
    """execute() does not re-fetch dates/periods already in the DB."""
    today = date(2026, 1, 15)
    # Pre-populate all daily dates and monthly periods
    daily = [today - timedelta(days=i) for i in range(365)]
    monthly: dict[str, list[tuple[int, int]]] = {
        "IPC_CL": [
            (d.year, d.month)
            for d in [
                date(today.year, today.month, 1) - timedelta(days=30 * i)
                for i in range(12)
            ]
        ]
    }
    repository = StubMarketDataRepository(
        existing_dates={"USD": daily, "EUR": daily, "UF": daily, "UTM": daily},
        existing_periods=monthly,
    )
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    assert result.upserted_exchange_rates == 0
    assert result.upserted_economic_indices == 0
    assert repository.refreshed == []


async def test_execute_request_syncs_specific_gaps() -> None:
    """execute_request() syncs only the explicitly requested missing data."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
    )

    request = MarketDataSyncRequestDTO(
        exchange_rate_dates={"USD": [date(2026, 1, 5), date(2026, 1, 6)]},
        economic_index_periods={"IPC_CL": [(2026, 1)]},
    )
    result = await use_case.execute_request(request)

    assert result.requested_exchange_rates == 2
    assert result.requested_economic_indices == 1
    assert result.upserted_exchange_rates == 2
    assert result.upserted_economic_indices == 1


async def test_execute_request_skips_empty_lists() -> None:
    """execute_request() is a no-op when all lists are empty."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
    )

    result = await use_case.execute_request(
        MarketDataSyncRequestDTO(
            exchange_rate_dates={"USD": []},
            economic_index_periods={"IPC_CL": []},
        )
    )

    assert result.upserted_exchange_rates == 0
    assert result.upserted_economic_indices == 0
    assert repository.refreshed == []


async def test_execute_request_skips_when_provider_returns_nothing() -> None:
    """execute_request() does not call refresh_rates if the provider returns nothing."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        EmptyFxProvider(),  # type: ignore[arg-type]
        EmptyIndexProvider(),  # type: ignore[arg-type]
    )

    result = await use_case.execute_request(
        MarketDataSyncRequestDTO(
            exchange_rate_dates={"USD": [date(2026, 1, 5)]},
            economic_index_periods={"IPC_CL": [(2026, 1)]},
        )
    )

    assert result.upserted_exchange_rates == 0
    assert result.upserted_economic_indices == 0
    assert repository.refreshed == []


async def test_collect_remaining_request_returns_none_when_all_synced() -> None:
    """collect_remaining_request returns None when no gaps remain."""
    today = date(2026, 1, 15)
    # Pre-fill the DB so everything is present
    repository = StubMarketDataRepository(
        existing_dates={"USD": [date(2026, 1, 5)]},
        existing_periods={"IPC_CL": [(2026, 1)]},
    )
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    request = MarketDataSyncRequestDTO(
        exchange_rate_dates={"USD": [date(2026, 1, 5)]},
        economic_index_periods={"IPC_CL": [(2026, 1)]},
    )
    remaining = await use_case.collect_remaining_request(request)
    assert remaining is None


async def test_collect_remaining_request_returns_gaps() -> None:
    """collect_remaining_request returns still-missing entries after a sync."""
    repository = StubMarketDataRepository()  # empty DB — nothing persisted
    use_case = SyncRecentMarketData(
        repository,
        EmptyFxProvider(),  # type: ignore[arg-type]
        EmptyIndexProvider(),  # type: ignore[arg-type]
    )

    request = MarketDataSyncRequestDTO(
        exchange_rate_dates={"USD": [date(2026, 1, 5)]},
        economic_index_periods={"IPC_CL": [(2026, 1)]},
    )
    result, remaining = await use_case.execute_request_and_collect_remaining(request)

    assert result.upserted_exchange_rates == 0
    assert remaining is not None
    assert remaining.exchange_rate_dates["USD"] == [date(2026, 1, 5)]
    assert remaining.economic_index_periods["IPC_CL"] == [(2026, 1)]


async def test_collect_remaining_request_skips_empty_date_and_period_lists() -> None:
    """collect_remaining_request skips currency/index codes with empty request lists."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
    )

    request = MarketDataSyncRequestDTO(
        exchange_rate_dates={"USD": []},
        economic_index_periods={"IPC_CL": []},
    )
    remaining = await use_case.collect_remaining_request(request)

    # Empty request lists → nothing is missing → None returned
    assert remaining is None
