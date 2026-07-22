"""Tests for the SyncRecentMarketData use case."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ExchangeRateWriteDTO,
    IncomeTaxBracketDTO,
    IncomeTaxBracketWriteDTO,
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
        unconfirmed_dates: dict[str, list[date]] | None = None,
    ) -> None:
        """Initialize the instance."""
        self._existing_dates = existing_dates or {}
        self._existing_periods = existing_periods or {}
        self._unconfirmed_dates = unconfirmed_dates or {}
        self.refreshed: list[RefreshRatesCommandDTO] = []

    async def list_exchange_rate_dates(
        self, currency_code: str, start: date, end: date
    ) -> list[date]:
        """List exchange rate dates."""
        return self._existing_dates.get(currency_code, [])

    async def list_unconfirmed_rate_dates(
        self, currency_code: str, start: date, end: date
    ) -> list[date]:
        """List unconfirmed rate dates."""
        return self._unconfirmed_dates.get(currency_code, [])

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


class StubReferenceDataRepository:
    """Test double for ReferenceDataRepository with controllable bracket data."""

    def __init__(self, existing_years: set[int] | None = None) -> None:
        """Initialize the instance."""
        self._existing_years = existing_years or set()
        self.upserted: list[IncomeTaxBracketWriteDTO] = []

    async def list_income_tax_brackets(
        self, year: int | None = None
    ) -> list[IncomeTaxBracketDTO]:
        """Return a non-empty list for years already in the DB, empty otherwise."""
        if year is not None and year not in self._existing_years:
            return []
        return [
            IncomeTaxBracketDTO(
                valid_from=date(year or 2026, 1, 1),
                valid_to=None,
                lower_bound_utm=Decimal("0"),
                upper_bound_utm=None,
                marginal_rate=Decimal("0.04"),
                rebate_utm=Decimal("0"),
            )
        ]

    async def upsert_income_tax_brackets(
        self, brackets: list[IncomeTaxBracketWriteDTO]
    ) -> int:
        """Capture upserted brackets and return count."""
        self.upserted.extend(brackets)
        return len(brackets)

    async def list_currencies(self) -> list[object]:
        """List currencies."""
        raise AssertionError("not used")

    async def get_income_tax_bracket(self, *args: object) -> None:
        """Get income tax bracket."""
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


class StubBracketProvider:
    """Test double for IncomeTaxBracketProvider returning one bracket per year."""

    async def fetch_income_tax_brackets(
        self, year: int
    ) -> list[IncomeTaxBracketWriteDTO]:
        """Handle fetch income tax brackets."""
        return [
            IncomeTaxBracketWriteDTO(
                valid_from=date(year, 1, 1),
                valid_to=None,
                lower_bound_utm=Decimal("0"),
                upper_bound_utm=None,
                marginal_rate=Decimal("0.04"),
                rebate_utm=Decimal("0"),
            )
        ]


def _make_default_use_case(
    today: date,
    repository: StubMarketDataRepository | None = None,
) -> SyncRecentMarketData:
    """Build SyncRecentMarketData with standard stubs and a fixed today."""
    return SyncRecentMarketData(
        repository or StubMarketDataRepository(),
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        StubReferenceDataRepository(existing_years={2025, 2026}),
        StubBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )


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


class EmptyBracketProvider:
    """Test double for IncomeTaxBracketProvider returning no brackets."""

    async def fetch_income_tax_brackets(
        self, year: int
    ) -> list[IncomeTaxBracketWriteDTO]:
        """Handle fetch income tax brackets."""
        return []


@pytest.mark.asyncio
async def test_execute_syncs_missing_entries() -> None:
    """execute() fetches and persists rates that are absent from the DB."""
    today = date(2026, 1, 15)
    repository = StubMarketDataRepository()
    reference_repository = StubReferenceDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        reference_repository,
        StubBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    assert isinstance(result, SyncRecentMarketDataResultDTO)
    assert result.upserted_exchange_rates > 0
    assert result.upserted_economic_indices > 0
    assert len(repository.refreshed) > 0


@pytest.mark.asyncio
async def test_execute_skips_already_existing_entries() -> None:
    """execute() does not re-fetch dates/periods already in the DB."""
    today = date(2026, 1, 15)
    # Pre-populate all daily dates and monthly periods.
    # UF also needs the 35-day forward window pre-populated since it requests future
    # dates for currencies in FORWARD_DAILY_RATE_CODES.
    daily = [today - timedelta(days=i) for i in range(365)]
    uf_forward = [today + timedelta(days=i) for i in range(1, 36)]
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
        existing_dates={
            "USD": daily,
            "EUR": daily,
            "UF": daily + uf_forward,
            "UTM": daily,
        },
        existing_periods=monthly,
    )
    # Pre-populate brackets for both years in the 12-month window (2025, 2026)
    reference_repository = StubReferenceDataRepository(existing_years={2025, 2026})
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        reference_repository,
        StubBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    assert result.upserted_exchange_rates == 0
    assert result.upserted_economic_indices == 0
    assert result.upserted_brackets == 0
    assert repository.refreshed == []
    assert reference_repository.upserted == []


@pytest.mark.asyncio
async def test_execute_syncs_missing_brackets() -> None:
    """execute() fetches and persists brackets for years not yet in the DB."""
    today = date(2026, 1, 15)
    reference_repository = StubReferenceDataRepository()  # empty — no brackets stored
    use_case = SyncRecentMarketData(
        StubMarketDataRepository(),
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        reference_repository,
        StubBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    # The 12-month window for 2026-01-15 spans 2025 and 2026 → 2 years upserted
    assert result.upserted_brackets == 2
    assert len(reference_repository.upserted) == 2


@pytest.mark.asyncio
async def test_execute_skips_years_with_existing_brackets() -> None:
    """execute() does not re-fetch brackets for years already in the DB."""
    today = date(2026, 1, 15)
    reference_repository = StubReferenceDataRepository(existing_years={2025, 2026})
    use_case = SyncRecentMarketData(
        StubMarketDataRepository(),
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        reference_repository,
        StubBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    assert result.upserted_brackets == 0
    assert reference_repository.upserted == []


@pytest.mark.asyncio
async def test_execute_skips_when_bracket_provider_returns_nothing() -> None:
    """execute() does not upsert when the provider returns no brackets."""
    today = date(2026, 1, 15)
    reference_repository = StubReferenceDataRepository()  # empty DB
    use_case = SyncRecentMarketData(
        StubMarketDataRepository(),
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        reference_repository,
        EmptyBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    assert result.upserted_brackets == 0
    assert reference_repository.upserted == []


@pytest.mark.asyncio
async def test_execute_request_syncs_specific_gaps() -> None:
    """execute_request() syncs only the explicitly requested missing data."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        StubReferenceDataRepository(),
        StubBracketProvider(),  # type: ignore[arg-type]
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


@pytest.mark.asyncio
async def test_execute_request_skips_empty_lists() -> None:
    """execute_request() is a no-op when all lists are empty."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        StubReferenceDataRepository(),
        StubBracketProvider(),  # type: ignore[arg-type]
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


@pytest.mark.asyncio
async def test_execute_request_skips_when_provider_returns_nothing() -> None:
    """execute_request() does not call refresh_rates if the provider returns nothing."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        EmptyFxProvider(),  # type: ignore[arg-type]
        EmptyIndexProvider(),  # type: ignore[arg-type]
        StubReferenceDataRepository(),
        StubBracketProvider(),  # type: ignore[arg-type]
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


@pytest.mark.asyncio
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
        StubReferenceDataRepository(),
        StubBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    request = MarketDataSyncRequestDTO(
        exchange_rate_dates={"USD": [date(2026, 1, 5)]},
        economic_index_periods={"IPC_CL": [(2026, 1)]},
    )
    remaining = await use_case.collect_remaining_request(request)
    assert remaining is None


@pytest.mark.asyncio
async def test_collect_remaining_request_returns_gaps() -> None:
    """collect_remaining_request returns still-missing entries after a sync."""
    repository = StubMarketDataRepository()  # empty DB — nothing persisted
    use_case = SyncRecentMarketData(
        repository,
        EmptyFxProvider(),  # type: ignore[arg-type]
        EmptyIndexProvider(),  # type: ignore[arg-type]
        StubReferenceDataRepository(),
        StubBracketProvider(),  # type: ignore[arg-type]
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


@pytest.mark.asyncio
async def test_collect_remaining_request_skips_empty_date_and_period_lists() -> None:
    """collect_remaining_request skips currency/index codes with empty request lists."""
    repository = StubMarketDataRepository()
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        StubReferenceDataRepository(),
        StubBracketProvider(),  # type: ignore[arg-type]
    )

    request = MarketDataSyncRequestDTO(
        exchange_rate_dates={"USD": []},
        economic_index_periods={"IPC_CL": []},
    )
    remaining = await use_case.collect_remaining_request(request)

    # Empty request lists → nothing is missing → None returned
    assert remaining is None


@pytest.mark.asyncio
async def test_execute_refetches_same_day_dates() -> None:
    """execute() re-fetches daily rates stored on the same calendar day as rate_date."""
    today = date(2026, 1, 15)
    # USD has a stored rate for today, but it was fetched same-day → not stable
    repository = StubMarketDataRepository(
        existing_dates={"USD": [today], "EUR": [], "UF": []},
        unconfirmed_dates={"USD": [today]},
    )
    use_case = SyncRecentMarketData(
        repository,
        StubFxProvider(),  # type: ignore[arg-type]
        StubIndexProvider(),  # type: ignore[arg-type]
        StubReferenceDataRepository(existing_years={2025, 2026}),
        StubBracketProvider(),  # type: ignore[arg-type]
        today_provider=lambda: today,
    )

    result = await use_case.execute()

    # today's USD rate was same-day → re-fetched → upserted
    upserted_usd_dates = [
        entry.rate_date
        for cmd in repository.refreshed
        for entry in cmd.exchange_rates
        if entry.currency_code == "USD"
    ]
    assert today in upserted_usd_dates
    assert result.upserted_exchange_rates > 0


@pytest.mark.asyncio
async def test_execute_requests_forward_dates_for_uf_only() -> None:
    """execute() includes future dates in UF requests but not in USD or EUR."""
    today = date(2026, 1, 15)
    repository = StubMarketDataRepository()
    use_case = _make_default_use_case(today, repository)

    await use_case.execute()

    all_requested: dict[str, set[date]] = {}
    for cmd in repository.refreshed:
        for entry in cmd.exchange_rates:
            all_requested.setdefault(entry.currency_code, set()).add(entry.rate_date)

    future_date = today + timedelta(days=1)
    assert future_date in all_requested.get("UF", set()), (
        "UF should request forward dates"
    )
    assert future_date not in all_requested.get("USD", set()), (
        "USD should not request forward dates"
    )
    assert future_date not in all_requested.get("EUR", set()), (
        "EUR should not request forward dates"
    )


@pytest.mark.asyncio
async def test_execute_custom_lookback_limits_requested_window() -> None:
    """execute(lookback_days=7) requests only 7 days of history, not 365."""
    today = date(2026, 1, 15)
    cutoff = today - timedelta(days=7)
    repository = StubMarketDataRepository()
    use_case = _make_default_use_case(today, repository)

    await use_case.execute(lookback_days=7, forward_days=0)

    usd_dates = {
        entry.rate_date
        for cmd in repository.refreshed
        for entry in cmd.exchange_rates
        if entry.currency_code == "USD"
    }
    assert len(usd_dates) == 7
    assert today in usd_dates
    assert cutoff not in usd_dates, (
        "dates before the 7-day window must not be requested"
    )
