"""Tests for the RefreshRates use case."""

from datetime import date
from decimal import Decimal

import pytest

from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ExchangeRateWriteDTO,
    ProviderEconomicIndexRequestDTO,
    ProviderExchangeRateRequestDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)
from financial_data.application.use_cases.refresh_rates import RefreshRates


class StubMarketDataRepository:
    """Test double for MarketDataRepository."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self.command: RefreshRatesCommandDTO | None = None

    async def list_exchange_rates(
        self, currency_code: str | None = None
    ) -> list[object]:
        """List exchange rates."""
        raise AssertionError("not used")

    async def list_economic_indices(self, code: str | None = None) -> list[object]:
        """List economic indices."""
        raise AssertionError("not used")

    async def list_economic_index_periods(
        self, code: str, ranges: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """List economic index periods."""
        raise AssertionError("not used")

    async def get_exchange_rate_value(
        self, currency_code: str, rate_date: date
    ) -> Decimal | None:
        """Get exchange rate value."""
        raise AssertionError("not used")

    async def get_economic_index_value(
        self, code: str, year: int, month: int
    ) -> Decimal | None:
        """Get economic index value."""
        raise AssertionError("not used")

    async def list_exchange_rate_dates(
        self, currency_code: str, start_date: date, end_date: date
    ) -> list[date]:
        """List exchange rate dates."""
        raise AssertionError("not used")

    async def list_unconfirmed_rate_dates(
        self, currency_code: str, start_date: date, end_date: date
    ) -> list[date]:
        """List unconfirmed rate dates."""
        raise AssertionError("not used")

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Refresh rates."""
        self.command = command
        return RefreshRatesResultDTO(
            upserted_exchange_rates=len(command.exchange_rates),
            upserted_economic_indices=len(command.economic_indices),
        )


class StubFxProvider:
    """Test double for FxRateProvider."""

    async def fetch_rate_entry(
        self, currency_code: str, rate_date: date
    ) -> ExchangeRateWriteDTO | None:
        """Handle fetch rate entry."""
        if currency_code == "UF":
            return ExchangeRateWriteDTO(
                currency_code="UF",
                rate_date=rate_date,
                value_clp=Decimal("38000"),
                source="mindicador",
            )
        return None


class StubEconomicIndexProvider:
    """Test double for EconomicIndexProvider."""

    async def fetch_index(
        self, code: str, period_year: int, period_month: int
    ) -> EconomicIndexWriteDTO | None:
        """Handle fetch index."""
        if code == "IPC_CL":
            return EconomicIndexWriteDTO(
                code="IPC_CL",
                period_year=period_year,
                period_month=period_month,
                index_value=Decimal("112.340000"),
                monthly_change=Decimal("0.7000"),
                yearly_change=Decimal("4.1000"),
                base_period="2023=100",
                source="sii",
            )
        return None


@pytest.mark.asyncio
async def test_refresh_rates_requires_non_empty_payload() -> None:
    """Test refresh rates requires non empty payload."""
    with pytest.raises(
        ValueError,
        match="At least one exchange rate or economic index entry is required.",
    ):
        await RefreshRates(StubMarketDataRepository()).execute(
            RefreshRatesCommandDTO(exchange_rates=[], economic_indices=[])
        )


@pytest.mark.asyncio
async def test_refresh_rates_normalizes_codes_and_delegates() -> None:
    """Test refresh rates normalizes codes and delegates."""
    repository = StubMarketDataRepository()
    use_case = RefreshRates(repository)

    result = await use_case.execute(
        RefreshRatesCommandDTO(
            exchange_rates=[
                ExchangeRateWriteDTO(
                    currency_code=" uf ",
                    rate_date=date(2026, 1, 31),
                    value_clp=Decimal("38000"),
                    source="",
                )
            ],
            economic_indices=[
                EconomicIndexWriteDTO(
                    code=" ipc_cl ",
                    period_year=2026,
                    period_month=1,
                    index_value=Decimal("112.340000"),
                    monthly_change=Decimal("0.7000"),
                    yearly_change=Decimal("4.1000"),
                    base_period="",
                    source="",
                )
            ],
        )
    )

    assert result == RefreshRatesResultDTO(
        upserted_exchange_rates=1, upserted_economic_indices=1
    )
    assert repository.command is not None
    assert repository.command.exchange_rates[0].currency_code == "UF"
    assert repository.command.exchange_rates[0].source == "manual"
    assert repository.command.economic_indices[0].code == "IPC_CL"
    assert repository.command.economic_indices[0].base_period == "DIC-2018"
    assert repository.command.economic_indices[0].source == "manual"


@pytest.mark.asyncio
async def test_refresh_rates_fetches_provider_entries_and_keeps_manual_values() -> None:
    """Refresh rates fetches provider-backed entries; manual values take precedence."""
    repository = StubMarketDataRepository()
    result = await RefreshRates(
        repository,
        fx_provider=StubFxProvider(),  # type: ignore[arg-type]
        economic_index_provider=StubEconomicIndexProvider(),  # type: ignore[arg-type]
    ).execute(
        RefreshRatesCommandDTO(
            exchange_rates=[
                ExchangeRateWriteDTO(
                    currency_code="uf",
                    rate_date=date(2026, 1, 31),
                    value_clp=Decimal("38100"),
                    source="manual",
                )
            ],
            provider_exchange_rates=[
                ProviderExchangeRateRequestDTO(
                    currency_code=" uf ", rate_date=date(2026, 1, 31)
                )
            ],
            provider_economic_indices=[
                ProviderEconomicIndexRequestDTO(
                    code=" ipc_cl ", period_year=2026, period_month=1
                )
            ],
        )
    )

    assert result == RefreshRatesResultDTO(
        upserted_exchange_rates=1, upserted_economic_indices=1
    )
    assert repository.command is not None
    assert repository.command.exchange_rates == [
        ExchangeRateWriteDTO(
            currency_code="UF",
            rate_date=date(2026, 1, 31),
            value_clp=Decimal("38100"),
            source="manual",
        )
    ]
    assert repository.command.economic_indices == [
        EconomicIndexWriteDTO(
            code="IPC_CL",
            period_year=2026,
            period_month=1,
            index_value=Decimal("112.340000"),
            monthly_change=Decimal("0.7000"),
            yearly_change=Decimal("4.1000"),
            base_period="2023=100",
            source="sii",
        )
    ]


@pytest.mark.asyncio
async def test_refresh_rates_rejects_missing_provider_configuration_and_misses() -> (
    None
):
    """Test refresh rates rejects missing provider configuration and fetch misses."""
    with pytest.raises(
        ValueError, match="Exchange-rate provider chain is not configured."
    ):
        await RefreshRates(StubMarketDataRepository()).execute(
            RefreshRatesCommandDTO(
                provider_exchange_rates=[
                    ProviderExchangeRateRequestDTO(
                        currency_code="UF", rate_date=date(2026, 1, 31)
                    )
                ]
            )
        )

    with pytest.raises(
        ValueError, match="Exchange rate USD for 2026-01-31 could not be fetched"
    ):
        await RefreshRates(
            StubMarketDataRepository(),
            fx_provider=StubFxProvider(),  # type: ignore[arg-type]
            economic_index_provider=StubEconomicIndexProvider(),  # type: ignore[arg-type]
        ).execute(
            RefreshRatesCommandDTO(
                provider_exchange_rates=[
                    ProviderExchangeRateRequestDTO(
                        currency_code="USD", rate_date=date(2026, 1, 31)
                    )
                ]
            )
        )

    with pytest.raises(
        ValueError, match="Economic-index provider chain is not configured."
    ):
        await RefreshRates(
            StubMarketDataRepository(),
            fx_provider=StubFxProvider(),  # type: ignore[arg-type]
        ).execute(
            RefreshRatesCommandDTO(
                provider_economic_indices=[
                    ProviderEconomicIndexRequestDTO(
                        code="IPC_CL", period_year=2026, period_month=1
                    )
                ]
            )
        )

    with pytest.raises(
        ValueError, match="Economic index UF_CL for 2026-01 could not be fetched"
    ):
        await RefreshRates(
            StubMarketDataRepository(),
            fx_provider=StubFxProvider(),  # type: ignore[arg-type]
            economic_index_provider=StubEconomicIndexProvider(),  # type: ignore[arg-type]
        ).execute(
            RefreshRatesCommandDTO(
                provider_economic_indices=[
                    ProviderEconomicIndexRequestDTO(
                        code="UF_CL", period_year=2026, period_month=1
                    )
                ]
            )
        )
