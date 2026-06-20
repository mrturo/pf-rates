"""Use case for refreshing rates and economic indices."""

from dataclasses import dataclass

from financial_data.application.errors import (
    FinancialDataDependencyConfigurationError,
    FinancialDataDependencyError,
    FinancialDataValidationError,
)
from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ExchangeRateWriteDTO,
    ProviderEconomicIndexRequestDTO,
    ProviderExchangeRateRequestDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)
from financial_data.application.ports.rate_provider import (
    EconomicIndexProvider,
    FxRateProvider,
)
from financial_data.application.ports.market_data_repository import MarketDataRepository


@dataclass(slots=True)
class RefreshRates:
    """Store historical exchange rates and economic indices."""

    repository: MarketDataRepository
    fx_provider: FxRateProvider | None = None
    economic_index_provider: EconomicIndexProvider | None = None

    async def execute(self, command: RefreshRatesCommandDTO) -> RefreshRatesResultDTO:
        """Handle execute."""
        if (
            not command.exchange_rates
            and not command.economic_indices
            and not command.provider_exchange_rates
            and not command.provider_economic_indices
        ):
            raise FinancialDataValidationError(
                "At least one exchange rate or economic index entry is required."
            )

        exchange_rates: list[ExchangeRateWriteDTO] = [
            ExchangeRateWriteDTO(
                currency_code=item.currency_code.strip().upper(),
                rate_date=item.rate_date,
                value_clp=item.value_clp,
                source=item.source.strip() or "manual",
            )
            for item in command.exchange_rates
        ]
        economic_indices: list[EconomicIndexWriteDTO] = [
            EconomicIndexWriteDTO(
                code=item.code.strip().upper(),
                period_year=item.period_year,
                period_month=item.period_month,
                index_value=item.index_value,
                monthly_change=item.monthly_change,
                yearly_change=item.yearly_change,
                base_period=item.base_period.strip() or "DIC-2018",
                source=item.source.strip() or "manual",
            )
            for item in command.economic_indices
        ]
        provider_exchange_rates: list[ProviderExchangeRateRequestDTO] = [
            ProviderExchangeRateRequestDTO(
                currency_code=item.currency_code.strip().upper(),
                rate_date=item.rate_date,
            )
            for item in command.provider_exchange_rates
        ]
        provider_economic_indices: list[ProviderEconomicIndexRequestDTO] = [
            ProviderEconomicIndexRequestDTO(
                code=item.code.strip().upper(),
                period_year=item.period_year,
                period_month=item.period_month,
            )
            for item in command.provider_economic_indices
        ]

        fetched_exchange_rates: list[ExchangeRateWriteDTO] = []
        if provider_exchange_rates:
            fx_provider = self.fx_provider
            if fx_provider is None:
                raise FinancialDataDependencyConfigurationError(
                    "Exchange-rate provider chain is not configured."
                )
            for rate_request in provider_exchange_rates:
                rate_entry = await fx_provider.fetch_rate_entry(
                    rate_request.currency_code, rate_request.rate_date
                )
                if rate_entry is None:
                    raise FinancialDataDependencyError(
                        "Exchange rate "
                        f"{rate_request.currency_code} for "
                        f"{rate_request.rate_date.isoformat()} "
                        "could not be fetched from configured providers."
                    )
                fetched_exchange_rates.append(rate_entry)

        fetched_economic_indices: list[EconomicIndexWriteDTO] = []
        if provider_economic_indices:
            economic_index_provider = self.economic_index_provider
            if economic_index_provider is None:
                raise FinancialDataDependencyConfigurationError(
                    "Economic-index provider chain is not configured."
                )
            for index_request in provider_economic_indices:
                index_entry = await economic_index_provider.fetch_index(
                    index_request.code,
                    index_request.period_year,
                    index_request.period_month,
                )
                if index_entry is None:
                    raise FinancialDataDependencyError(
                        "Economic index "
                        f"{index_request.code} for "
                        f"{index_request.period_year:04d}-"
                        f"{index_request.period_month:02d} "
                        "could not be fetched from configured providers."
                    )
                fetched_economic_indices.append(index_entry)

        normalized_command = RefreshRatesCommandDTO(
            exchange_rates=list(
                {
                    (rate_item.currency_code, rate_item.rate_date): rate_item
                    for rate_item in [*fetched_exchange_rates, *exchange_rates]
                }.values()
            ),
            economic_indices=list(
                {
                    (
                        index_item.code,
                        index_item.period_year,
                        index_item.period_month,
                    ): index_item
                    for index_item in [*fetched_economic_indices, *economic_indices]
                }.values()
            ),
        )
        return await self.repository.refresh_rates(normalized_command)
