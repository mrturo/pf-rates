"""Use case for retrieving an exchange rate value with external provider fallback."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_data.application.dto import RefreshRatesCommandDTO
from financial_data.application.errors import ExchangeRateNotFoundError
from financial_data.application.ports.market_data_repository import MarketDataRepository
from financial_data.application.ports.rate_provider import FxRateProvider


@dataclass(slots=True)
class GetExchangeRateValue:
    """Return the CLP value for a currency on a given date.

    Flow:
    1. Query the database.
    2. On miss, query the external provider chain.
    3. If the provider returns a value, persist it for future lookups.
    4. If neither source has the value, raise ExchangeRateNotFoundError.
    """

    repository: MarketDataRepository
    provider: FxRateProvider

    async def execute(self, currency_code: str, rate_date: date) -> Decimal:
        """Return the exchange rate value, falling back to the provider on a DB miss."""
        value = await self.repository.get_exchange_rate_value(currency_code, rate_date)
        if value is not None:
            return value

        entry = await self.provider.fetch_rate_entry(currency_code, rate_date)
        if entry is None:
            raise ExchangeRateNotFoundError(
                f"Exchange rate {currency_code} on {rate_date} not found."
            )

        await self.repository.refresh_rates(
            RefreshRatesCommandDTO(exchange_rates=[entry])
        )
        return entry.value_clp
