"""Integration tests for the pf-rates HTTP API.

Uses testcontainers (PostgreSQL) + httpx AsyncClient against the real FastAPI app.
The fixtures pg_url (session-scoped), db_session (function-scoped), and
http_client (function-scoped) are defined in conftest.py.
"""

from datetime import date
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from financial_data.application.dto import (
    IncomeTaxBracketWriteDTO,
    RefreshIncomeTaxBracketsCommandDTO,
    RefreshIncomeTaxBracketsResultDTO,
    RefreshRatesCommandDTO,
)
from financial_data.application.errors import FinancialDataDependencyError
from financial_data.infrastructure.db.repositories.market_data_repository import (
    SqlAlchemyMarketDataRepository,
)
from financial_data.infrastructure.db.repositories.reference_data_repository import (
    SqlAlchemyReferenceDataRepository,
)
from financial_data.interfaces.api.app import app
from financial_data.interfaces.api.dependencies import (
    get_refresh_income_tax_brackets_use_case,
    get_refresh_rates_use_case,
    get_session,
    get_sync_use_case,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def test_health(http_client: AsyncClient) -> None:
    """GET /health returns ok."""
    response = await http_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "pf-rates"}


# ---------------------------------------------------------------------------
# Currencies
# ---------------------------------------------------------------------------


async def test_list_currencies_returns_seed_data(http_client: AsyncClient) -> None:
    """GET /currencies returns the seeded currencies."""
    response = await http_client.get("/currencies")
    assert response.status_code == 200
    codes = {item["code"] for item in response.json()}
    assert {"CLP", "USD", "EUR", "UF", "UTM"} <= codes


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------


async def test_list_exchange_rates_empty(http_client: AsyncClient) -> None:
    """GET /exchange-rates returns empty list when no rates stored."""
    response = await http_client.get("/exchange-rates")
    assert response.status_code == 200
    assert response.json() == []


async def test_refresh_and_list_exchange_rates(http_client: AsyncClient) -> None:
    """POST /exchange-rates/refresh stores entries; GET /exchange-rates lists them."""
    post = await http_client.post(
        "/exchange-rates/refresh",
        json={
            "exchange_rates": [
                {
                    "currency_code": "USD",
                    "rate_date": "2026-01-15",
                    "value_clp": "980.500000",
                    "source": "test",
                }
            ]
        },
    )
    assert post.status_code == 200
    assert post.json()["upserted_exchange_rates"] == 1

    get = await http_client.get("/exchange-rates?currency_code=USD")
    assert get.status_code == 200
    items = get.json()
    assert len(items) >= 1
    assert any(item["currency_code"] == "USD" for item in items)
    assert Decimal(items[0]["value_clp"]) == Decimal("980.500000")


async def test_get_exchange_rate_value_found_and_not_found(
    http_client: AsyncClient,
) -> None:
    """GET /exchange-rates/value returns value or 404."""
    await http_client.post(
        "/exchange-rates/refresh",
        json={
            "exchange_rates": [
                {
                    "currency_code": "EUR",
                    "rate_date": "2026-02-01",
                    "value_clp": "1050.00",
                    "source": "test",
                }
            ]
        },
    )

    found = await http_client.get(
        "/exchange-rates/value?currency_code=EUR&rate_date=2026-02-01"
    )
    assert found.status_code == 200
    assert Decimal(found.json()["value_clp"]) == Decimal("1050.000000")

    missing = await http_client.get(
        "/exchange-rates/value?currency_code=EUR&rate_date=2025-01-01"
    )
    assert missing.status_code == 404


async def test_refresh_exchange_rates_rejects_unknown_currency(
    http_client: AsyncClient,
) -> None:
    """POST /exchange-rates/refresh returns 400 for unknown currency codes."""
    response = await http_client.post(
        "/exchange-rates/refresh",
        json={
            "exchange_rates": [
                {
                    "currency_code": "XXX",
                    "rate_date": "2026-01-01",
                    "value_clp": "1.0",
                    "source": "test",
                }
            ]
        },
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Economic indices
# ---------------------------------------------------------------------------


async def test_list_economic_indices_empty(http_client: AsyncClient) -> None:
    """GET /economic-indices returns empty list when no indices stored."""
    response = await http_client.get("/economic-indices")
    assert response.status_code == 200
    assert response.json() == []


async def test_refresh_and_list_economic_indices(http_client: AsyncClient) -> None:
    """POST /economic-indices/refresh stores entries; GET retrieves them."""
    post = await http_client.post(
        "/economic-indices/refresh",
        json={
            "economic_indices": [
                {
                    "code": "IPC_CL",
                    "period_year": 2026,
                    "period_month": 3,
                    "index_value": "112.50",
                    "monthly_change": "0.3",
                    "yearly_change": "3.1",
                    "base_period": "2023=100",
                    "source": "test",
                }
            ]
        },
    )
    assert post.status_code == 200
    assert post.json()["upserted_economic_indices"] == 1

    get = await http_client.get("/economic-indices?code=IPC_CL")
    assert get.status_code == 200
    items = get.json()
    assert any(
        item["period_year"] == 2026 and item["period_month"] == 3 for item in items
    )


async def test_get_economic_index_value_found_and_not_found(
    http_client: AsyncClient,
) -> None:
    """GET /economic-indices/value returns value or 404."""
    await http_client.post(
        "/economic-indices/refresh",
        json={
            "economic_indices": [
                {
                    "code": "IPC_CL",
                    "period_year": 2025,
                    "period_month": 12,
                    "index_value": "111.80",
                    "source": "test",
                }
            ]
        },
    )

    found = await http_client.get(
        "/economic-indices/value?code=IPC_CL&year=2025&month=12"
    )
    assert found.status_code == 200
    assert Decimal(found.json()["index_value"]) == Decimal("111.800000")

    missing = await http_client.get(
        "/economic-indices/value?code=IPC_CL&year=1999&month=1"
    )
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Income tax brackets
# ---------------------------------------------------------------------------


async def test_income_tax_brackets_roundtrip(
    http_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Bracket upsert via repository + list and lookup via HTTP endpoints."""
    repo = SqlAlchemyReferenceDataRepository(db_session)
    count = await repo.upsert_income_tax_brackets(
        [
            IncomeTaxBracketWriteDTO(
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 1, 31),
                lower_bound_utm=Decimal("0.0000"),
                upper_bound_utm=Decimal("13.5000"),
                marginal_rate=Decimal("0.000000"),
                rebate_utm=Decimal("0.0000"),
            ),
            IncomeTaxBracketWriteDTO(
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 1, 31),
                lower_bound_utm=Decimal("13.5000"),
                upper_bound_utm=Decimal("30.0000"),
                marginal_rate=Decimal("0.040000"),
                rebate_utm=Decimal("0.5400"),
            ),
            IncomeTaxBracketWriteDTO(
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 1, 31),
                lower_bound_utm=Decimal("30.0000"),
                upper_bound_utm=None,
                marginal_rate=Decimal("0.400000"),
                rebate_utm=Decimal("38.8370"),
            ),
        ]
    )
    assert count == 3

    # List by year
    list_response = await http_client.get("/income-tax-brackets/list?year=2026")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 3

    # Lookup: taxable_base_utm=20 → bracket [13.5, 30)
    lookup = await http_client.get(
        "/income-tax-brackets?payment_date=2026-01-15&taxable_base_utm=20"
    )
    assert lookup.status_code == 200
    data = lookup.json()
    assert Decimal(data["lower_bound_utm"]) == Decimal("13.5000")
    assert Decimal(data["marginal_rate"]) == Decimal("0.040000")

    # Lookup: 404 when no bracket exists for the date
    not_found = await http_client.get(
        "/income-tax-brackets?payment_date=2000-01-01&taxable_base_utm=20"
    )
    assert not_found.status_code == 404


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


async def test_sync_endpoint_runs_without_error(http_client: AsyncClient) -> None:
    """POST /sync completes successfully (stub provider returns zeros)."""
    response = await http_client.post("/sync", json={})
    assert response.status_code == 200
    body = response.json()
    assert "exchange_rates_upserted" in body
    assert "economic_indices_upserted" in body


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


async def test_refresh_exchange_rates_rejects_empty_payload(
    http_client: AsyncClient,
) -> None:
    """POST /exchange-rates/refresh with empty lists returns 400."""
    response = await http_client.post(
        "/exchange-rates/refresh",
        json={"exchange_rates": [], "fetch_exchange_rates": []},
    )
    assert response.status_code == 400


async def test_get_session_yields_async_session(
    pg_url: str, monkeypatch: object
) -> None:
    """get_session yields a real AsyncSession when SessionLocal is configured."""
    import financial_data.interfaces.api.dependencies as deps_module
    from sqlalchemy.ext.asyncio import (
        AsyncSession as _AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    engine = create_async_engine(pg_url)
    test_factory = async_sessionmaker(
        engine, class_=_AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(deps_module, "SessionLocal", test_factory)  # type: ignore[attr-defined]
    try:
        async for session in deps_module.get_session():
            assert isinstance(session, _AsyncSession)
            break
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Repository coverage — list_exchange_rate_dates & list_economic_index_periods
# ---------------------------------------------------------------------------


async def test_list_exchange_rate_dates_returns_stored_dates(
    db_session: AsyncSession,
) -> None:
    """list_exchange_rate_dates returns only dates within [start, end]."""
    from financial_data.application.dto import ExchangeRateWriteDTO

    repo = SqlAlchemyMarketDataRepository(db_session)
    await repo.refresh_rates(
        RefreshRatesCommandDTO(
            exchange_rates=[
                ExchangeRateWriteDTO(
                    currency_code="USD",
                    rate_date=date(2026, 3, 10),
                    value_clp=Decimal("980.00"),
                    source="test",
                )
            ]
        )
    )
    stored = await repo.list_exchange_rate_dates(
        "USD", date(2026, 3, 1), date(2026, 3, 31)
    )
    assert date(2026, 3, 10) in stored


async def test_list_economic_index_periods_returns_stored_periods(
    db_session: AsyncSession,
) -> None:
    """list_economic_index_periods returns periods that exist in the DB."""
    from financial_data.application.dto import EconomicIndexWriteDTO

    repo = SqlAlchemyMarketDataRepository(db_session)
    await repo.refresh_rates(
        RefreshRatesCommandDTO(
            economic_indices=[
                EconomicIndexWriteDTO(
                    code="IPC_CL",
                    period_year=2026,
                    period_month=4,
                    index_value=Decimal("112.00"),
                    source="test",
                )
            ]
        )
    )
    stored = await repo.list_economic_index_periods("IPC_CL", [(2026, 4), (2026, 5)])
    assert (2026, 4) in stored
    assert (2026, 5) not in stored


# ---------------------------------------------------------------------------
# Repository coverage — upsert_income_tax_brackets with empty list
# ---------------------------------------------------------------------------


async def test_list_economic_index_periods_empty_ranges_returns_empty(
    db_session: AsyncSession,
) -> None:
    """list_economic_index_periods([]) returns [] without querying the DB."""
    repo = SqlAlchemyMarketDataRepository(db_session)
    result = await repo.list_economic_index_periods("IPC_CL", [])
    assert result == []


async def test_upsert_income_tax_brackets_empty_returns_zero(
    db_session: AsyncSession,
) -> None:
    """upsert_income_tax_brackets([]) returns 0 without touching the DB."""
    repo = SqlAlchemyReferenceDataRepository(db_session)
    count = await repo.upsert_income_tax_brackets([])
    assert count == 0


# ---------------------------------------------------------------------------
# Route coverage — income-tax-brackets/refresh (success and error)
# ---------------------------------------------------------------------------


async def test_refresh_income_tax_brackets_route_success(pg_url: str) -> None:
    """POST /income-tax-brackets/refresh returns 200 with upserted count."""
    from tests.conftest import _TC_ENGINE_KWARGS  # type: ignore[attr-defined]

    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    class _StubRefreshBrackets:
        async def execute(
            self, cmd: RefreshIncomeTaxBracketsCommandDTO
        ) -> RefreshIncomeTaxBracketsResultDTO:
            """Return a fixed upserted count."""
            return RefreshIncomeTaxBracketsResultDTO(
                year=cmd.year, refreshed_months=1, upserted_brackets=3
            )

    def _stub_get_session_override():  # type: ignore[return]
        async def _inner():  # type: ignore[return]
            async with session_factory() as session:
                yield session

        return _inner

    app.dependency_overrides[get_session] = _stub_get_session_override()
    app.dependency_overrides[get_sync_use_case] = lambda: None  # type: ignore[assignment, return-value]
    app.dependency_overrides[get_refresh_income_tax_brackets_use_case] = lambda: (
        _StubRefreshBrackets()
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/income-tax-brackets/refresh", json={"year": 2026}
            )
        assert response.status_code == 200
        assert response.json()["upserted"] == 3
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_refresh_income_tax_brackets_route_propagates_error(
    pg_url: str,
) -> None:
    """POST /income-tax-brackets/refresh returns 502 on FinancialDataError."""
    from tests.conftest import _TC_ENGINE_KWARGS  # type: ignore[attr-defined]

    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    class _FailingRefreshBrackets:
        async def execute(
            self, cmd: RefreshIncomeTaxBracketsCommandDTO
        ) -> RefreshIncomeTaxBracketsResultDTO:
            """Raise a dependency error to simulate provider failure."""
            raise FinancialDataDependencyError("provider unavailable")

    def _stub_get_session_override():  # type: ignore[return]
        async def _inner():  # type: ignore[return]
            async with session_factory() as session:
                yield session

        return _inner

    app.dependency_overrides[get_session] = _stub_get_session_override()
    app.dependency_overrides[get_sync_use_case] = lambda: None  # type: ignore[assignment, return-value]
    app.dependency_overrides[get_refresh_income_tax_brackets_use_case] = lambda: (
        _FailingRefreshBrackets()
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/income-tax-brackets/refresh", json={"year": 2026}
            )
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Route coverage — economic-indices/refresh error path
# ---------------------------------------------------------------------------


async def test_refresh_economic_indices_route_propagates_error(pg_url: str) -> None:
    """POST /economic-indices/refresh returns 502 on FinancialDataError."""
    from tests.conftest import _TC_ENGINE_KWARGS  # type: ignore[attr-defined]

    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    class _FailingRefreshRates:
        async def execute(self, cmd: object) -> None:  # type: ignore[return]
            """Raise a dependency error to simulate provider failure."""
            raise FinancialDataDependencyError("provider unavailable")

    def _stub_get_session_override():  # type: ignore[return]
        async def _inner():  # type: ignore[return]
            async with session_factory() as session:
                yield session

        return _inner

    app.dependency_overrides[get_session] = _stub_get_session_override()
    app.dependency_overrides[get_sync_use_case] = lambda: None  # type: ignore[assignment, return-value]
    app.dependency_overrides[get_refresh_rates_use_case] = lambda: (
        _FailingRefreshRates()
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/economic-indices/refresh",
                json={
                    "economic_indices": [
                        {
                            "code": "IPC_CL",
                            "period_year": 2026,
                            "period_month": 1,
                            "index_value": "112.00",
                            "source": "test",
                        }
                    ]
                },
            )
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
