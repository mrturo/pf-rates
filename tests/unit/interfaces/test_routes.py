"""Unit tests for HTTP route handlers (no database required).

Integration tests covering these routes exist in tests/integration/ but are
skipped when Docker is unavailable. These unit tests use hand-rolled stubs and
FastAPI dependency overrides to reach the branches that integration tests cover,
ensuring 100% coverage in CI environments without Docker.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from httpx import ASGITransport, AsyncClient

from financial_data.application.dto import (
    CurrencyDTO,
    EconomicIndexDTO,
    ExchangeRateDTO,
    IncomeTaxBracketDTO,
    RefreshIncomeTaxBracketsCommandDTO,
    RefreshIncomeTaxBracketsResultDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
    SyncRecentMarketDataResultDTO,
)
from financial_data.application.errors import (
    ExchangeRateNotFoundError,
    FinancialDataDependencyError,
)
from financial_data.interfaces.api.app import app
from financial_data.interfaces.api.dependencies import (
    get_exchange_rate_value_use_case,
    get_market_data_repository,
    get_reference_data_repository,
    get_refresh_income_tax_brackets_use_case,
    get_refresh_rates_use_case,
    get_sync_use_case,
)
from tests.conftest import _ECONOMIC_INDICES_REFRESH_PAYLOAD

_AUTHED: dict[str, Any] = {
    "transport": ASGITransport(app=app),
    "base_url": "http://test",
    "headers": {"X-API-Key": "test-key"},
}


async def _authed_post(url: str, payload: dict[str, Any]) -> Any:
    """POST to *url* with test-key auth and return the httpx Response."""
    async with AsyncClient(**_AUTHED) as client:
        return await client.post(url, json=payload)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubMarketDataRepository:
    """Stub MarketDataRepository returning configurable in-memory results."""

    def __init__(
        self,
        exchange_rates: list[ExchangeRateDTO] | None = None,
        economic_indices: list[EconomicIndexDTO] | None = None,
        exchange_rate_value: Decimal | None = None,
        economic_index_value: Decimal | None = None,
    ) -> None:
        self._exchange_rates = exchange_rates or []
        self._economic_indices = economic_indices or []
        self._exchange_rate_value = exchange_rate_value
        self._economic_index_value = economic_index_value

    async def list_exchange_rates(
        self, currency_code: str | None = None
    ) -> list[ExchangeRateDTO]:
        """Return preconfigured exchange rate list."""
        return self._exchange_rates

    async def get_exchange_rate_value(
        self, currency_code: str, rate_date: date
    ) -> Decimal | None:
        """Return preconfigured value or None."""
        return self._exchange_rate_value

    async def list_economic_indices(
        self, code: str | None = None
    ) -> list[EconomicIndexDTO]:
        """Return preconfigured economic index list."""
        return self._economic_indices

    async def get_economic_index_value(
        self, code: str, year: int, month: int
    ) -> Decimal | None:
        """Return preconfigured value or None."""
        return self._economic_index_value


class _StubRefreshRates:
    """Stub RefreshRates use case."""

    def __init__(self, result: RefreshRatesResultDTO) -> None:
        self._result = result

    async def execute(self, cmd: RefreshRatesCommandDTO) -> RefreshRatesResultDTO:
        """Return preconfigured result."""
        return self._result


class _StubReferenceDataRepository:
    """Stub ReferenceDataRepository returning configurable in-memory results."""

    def __init__(
        self,
        bracket: IncomeTaxBracketDTO | None = None,
        brackets: list[IncomeTaxBracketDTO] | None = None,
    ) -> None:
        self._bracket = bracket
        self._brackets = brackets or []

    async def get_income_tax_bracket(
        self, reference_date: date, taxable_base_utm: Decimal
    ) -> IncomeTaxBracketDTO | None:
        """Return preconfigured bracket or None."""
        return self._bracket

    async def list_income_tax_brackets(self, year: int) -> list[IncomeTaxBracketDTO]:
        """Return preconfigured bracket list."""
        return self._brackets

    async def list_currencies(self) -> list[CurrencyDTO]:
        """Return a single stub currency."""
        return [
            CurrencyDTO(code="USD", name="US Dollar", is_fiat=True, unit_kind="fiat")
        ]


class _StubRefreshRatesError:
    """Stub RefreshRates use case that raises FinancialDataDependencyError."""

    async def execute(self, cmd: RefreshRatesCommandDTO) -> RefreshRatesResultDTO:
        """Raise a provider error."""
        raise FinancialDataDependencyError("provider unavailable")


class _StubRefreshIncomeTaxBracketsError:
    """Stub RefreshIncomeTaxBrackets that raises FinancialDataDependencyError."""

    async def execute(
        self, cmd: RefreshIncomeTaxBracketsCommandDTO
    ) -> RefreshIncomeTaxBracketsResultDTO:
        """Raise a provider error."""
        raise FinancialDataDependencyError("provider unavailable")


class _StubRefreshIncomeTaxBrackets:
    """Stub RefreshIncomeTaxBrackets use case."""

    def __init__(self, result: RefreshIncomeTaxBracketsResultDTO) -> None:
        self._result = result

    async def execute(
        self, cmd: RefreshIncomeTaxBracketsCommandDTO
    ) -> RefreshIncomeTaxBracketsResultDTO:
        """Return preconfigured result."""
        return self._result


class _StubGetExchangeRateValue:
    """Stub GetExchangeRateValue use case."""

    def __init__(self, value: Decimal | None = None) -> None:
        self._value = value

    async def execute(self, currency_code: str, rate_date: date) -> Decimal:
        """Return value or raise ExchangeRateNotFoundError."""
        if self._value is None:
            raise ExchangeRateNotFoundError(
                f"Exchange rate {currency_code} on {rate_date} not found."
            )
        return self._value


class _StubSyncUseCase:
    """Stub SyncRecentMarketData use case."""

    async def execute(
        self,
        lookback_days: int | None = None,
        forward_days: int | None = None,
    ) -> SyncRecentMarketDataResultDTO:
        """Return fixed non-zero result."""
        return SyncRecentMarketDataResultDTO(
            requested_exchange_rates=5,
            requested_economic_indices=2,
            upserted_exchange_rates=3,
            upserted_economic_indices=1,
        )


# ---------------------------------------------------------------------------
# Exchange-rate route handlers
# ---------------------------------------------------------------------------


async def test_list_exchange_rates_serializes_non_empty_result() -> None:
    """GET /exchange-rates returns serialized items when repository is non-empty."""
    stub = _StubMarketDataRepository(
        exchange_rates=[
            ExchangeRateDTO(
                currency_code="USD",
                rate_date=date(2026, 1, 15),
                value_clp=Decimal("980.500000"),
                source="test",
            )
        ]
    )
    app.dependency_overrides[get_market_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get("/exchange-rates")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["currency_code"] == "USD"
        assert Decimal(items[0]["value_clp"]) == Decimal("980.500000")
    finally:
        app.dependency_overrides.clear()


async def test_get_exchange_rate_value_not_found_returns_404() -> None:
    """GET /exchange-rates/value returns 404 when neither DB nor provider has the rate.

    Stubs the full use case to avoid real provider calls.
    """
    stub = _StubGetExchangeRateValue(value=None)
    app.dependency_overrides[get_exchange_rate_value_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get(
                "/exchange-rates/value?currency_code=USD&rate_date=2026-01-01"
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_refresh_exchange_rates_returns_upserted_count() -> None:
    """POST /exchange-rates/refresh returns upserted counts from the use case."""
    stub = _StubRefreshRates(
        result=RefreshRatesResultDTO(
            upserted_exchange_rates=2, upserted_economic_indices=0
        )
    )
    app.dependency_overrides[get_refresh_rates_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        response = await _authed_post(
            "/exchange-rates/refresh",
            {
                "exchange_rates": [
                    {
                        "currency_code": "USD",
                        "rate_date": "2026-01-15",
                        "value_clp": "980.00",
                        "source": "test",
                    }
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["upserted_exchange_rates"] == 2
        assert body["upserted_economic_indices"] == 0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Economic-index route handlers
# ---------------------------------------------------------------------------


async def test_list_economic_indices_serializes_non_empty_result() -> None:
    """GET /economic-indices returns serialized items when repository is non-empty."""
    stub = _StubMarketDataRepository(
        economic_indices=[
            EconomicIndexDTO(
                code="IPC_CL",
                period_year=2026,
                period_month=3,
                index_value=Decimal("112.50"),
                monthly_change=Decimal("0.3"),
                yearly_change=None,
                base_period="DIC-2018",
                source="test",
            )
        ]
    )
    app.dependency_overrides[get_market_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get("/economic-indices")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["code"] == "IPC_CL"
        assert Decimal(items[0]["index_value"]) == Decimal("112.50")
        assert items[0]["monthly_change"] == "0.3"
        assert items[0]["yearly_change"] is None
    finally:
        app.dependency_overrides.clear()


async def test_get_economic_index_value_not_found_returns_404() -> None:
    """GET /economic-indices/value returns 404 when repository returns None."""
    stub = _StubMarketDataRepository(economic_index_value=None)
    app.dependency_overrides[get_market_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get(
                "/economic-indices/value?code=IPC_CL&year=2026&month=1"
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_refresh_economic_indices_returns_upserted_count() -> None:
    """POST /economic-indices/refresh returns upserted counts from the use case."""
    stub = _StubRefreshRates(
        result=RefreshRatesResultDTO(
            upserted_exchange_rates=0, upserted_economic_indices=1
        )
    )
    app.dependency_overrides[get_refresh_rates_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        response = await _authed_post(
            "/economic-indices/refresh", _ECONOMIC_INDICES_REFRESH_PAYLOAD
        )
        assert response.status_code == 200
        body = response.json()
        assert body["upserted_economic_indices"] == 1
        assert body["upserted_exchange_rates"] == 0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Income-tax-bracket route handlers
# ---------------------------------------------------------------------------


async def test_get_income_tax_bracket_not_found_returns_404() -> None:
    """GET /income-tax-brackets returns 404 when repository returns None."""
    stub = _StubReferenceDataRepository(bracket=None)
    app.dependency_overrides[get_reference_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get(
                "/income-tax-brackets?reference_date=2026-01-15&taxable_base_utm=20"
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_get_income_tax_bracket_found_returns_bracket() -> None:
    """GET /income-tax-brackets returns the matching bracket when found."""
    bracket = IncomeTaxBracketDTO(
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        lower_bound_utm=Decimal("13.5000"),
        upper_bound_utm=Decimal("30.0000"),
        marginal_rate=Decimal("0.040000"),
        rebate_utm=Decimal("0.5400"),
    )
    stub = _StubReferenceDataRepository(bracket=bracket)
    app.dependency_overrides[get_reference_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get(
                "/income-tax-brackets?reference_date=2026-01-15&taxable_base_utm=20"
            )
        assert response.status_code == 200
        data = response.json()
        assert Decimal(data["lower_bound_utm"]) == Decimal("13.5000")
        assert Decimal(data["marginal_rate"]) == Decimal("0.040000")
        assert Decimal(data["rebate_utm"]) == Decimal("0.5400")
    finally:
        app.dependency_overrides.clear()


async def test_list_income_tax_brackets_serializes_non_empty_result() -> None:
    """GET /income-tax-brackets/list returns serialized bracket items."""
    brackets = [
        IncomeTaxBracketDTO(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            lower_bound_utm=Decimal("0.0000"),
            upper_bound_utm=None,
            marginal_rate=Decimal("0.000000"),
            rebate_utm=Decimal("0.0000"),
        )
    ]
    stub = _StubReferenceDataRepository(brackets=brackets)
    app.dependency_overrides[get_reference_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get("/income-tax-brackets/list?year=2026")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["marginal_rate"] == "0.000000"
        assert items[0]["upper_bound_utm"] is None
    finally:
        app.dependency_overrides.clear()


async def test_refresh_income_tax_brackets_returns_upserted_count() -> None:
    """POST /income-tax-brackets/refresh returns upserted count from the use case."""
    stub = _StubRefreshIncomeTaxBrackets(
        result=RefreshIncomeTaxBracketsResultDTO(
            year=2026, refreshed_months=12, upserted_brackets=7
        )
    )
    app.dependency_overrides[get_refresh_income_tax_brackets_use_case] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.post(
                "/income-tax-brackets/refresh", json={"year": 2026}
            )
        assert response.status_code == 200
        assert response.json()["upserted"] == 7
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sync route handler
# ---------------------------------------------------------------------------


async def test_get_exchange_rate_value_found_returns_value() -> None:
    """GET /exchange-rates/value returns value_clp when repository returns a value."""
    stub = _StubMarketDataRepository(exchange_rate_value=Decimal("980.500000"))
    app.dependency_overrides[get_market_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get(
                "/exchange-rates/value?currency_code=USD&rate_date=2026-01-15"
            )
        assert response.status_code == 200
        assert Decimal(response.json()["value_clp"]) == Decimal("980.500000")
    finally:
        app.dependency_overrides.clear()


async def test_refresh_exchange_rates_error_returns_502() -> None:
    """POST /exchange-rates/refresh returns 502 on FinancialDataError."""
    app.dependency_overrides[get_refresh_rates_use_case] = lambda: (
        _StubRefreshRatesError()
    )
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        response = await _authed_post(
            "/exchange-rates/refresh",
            {
                "exchange_rates": [
                    {
                        "currency_code": "USD",
                        "rate_date": "2026-01-15",
                        "value_clp": "1.0",
                    }
                ]
            },
        )
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()


async def test_get_economic_index_value_found_returns_value() -> None:
    """GET /economic-indices/value returns index_value when repository returns it."""
    stub = _StubMarketDataRepository(economic_index_value=Decimal("112.500000"))
    app.dependency_overrides[get_market_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get(
                "/economic-indices/value?code=IPC_CL&year=2026&month=3"
            )
        assert response.status_code == 200
        assert Decimal(response.json()["index_value"]) == Decimal("112.500000")
    finally:
        app.dependency_overrides.clear()


async def test_refresh_economic_indices_error_returns_502() -> None:
    """POST /economic-indices/refresh returns 502 on FinancialDataError."""
    app.dependency_overrides[get_refresh_rates_use_case] = lambda: (
        _StubRefreshRatesError()
    )
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        response = await _authed_post(
            "/economic-indices/refresh",
            {
                "economic_indices": [
                    {
                        "code": "IPC_CL",
                        "period_year": 2026,
                        "period_month": 1,
                        "index_value": "112.00",
                    }
                ]
            },
        )
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()


async def test_refresh_income_tax_brackets_error_returns_502() -> None:
    """POST /income-tax-brackets/refresh returns 502 on FinancialDataError."""
    app.dependency_overrides[get_refresh_income_tax_brackets_use_case] = lambda: (
        _StubRefreshIncomeTaxBracketsError()
    )
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.post(
                "/income-tax-brackets/refresh", json={"year": 2026}
            )
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()


async def test_list_currencies_serializes_non_empty_result() -> None:
    """GET /currencies returns serialized CurrencyRead items."""
    stub = _StubReferenceDataRepository()
    app.dependency_overrides[get_reference_data_repository] = lambda: stub
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.get("/currencies")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["code"] == "USD"
        assert items[0]["is_fiat"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sync route handler
# ---------------------------------------------------------------------------


async def test_sync_market_data_returns_upserted_counts() -> None:
    """POST /sync returns all three upserted-count keys with correct values."""
    app.dependency_overrides[get_sync_use_case] = lambda: _StubSyncUseCase()
    try:
        async with AsyncClient(**_AUTHED) as client:
            response = await client.post("/sync", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["exchange_rates_upserted"] == 3
        assert body["economic_indices_upserted"] == 1
        assert body["brackets_upserted"] == 0
    finally:
        app.dependency_overrides.clear()
