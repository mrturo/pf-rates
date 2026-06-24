"""Use case for retrieving an exchange rate value with external provider fallback."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from financial_data.application.dto import RefreshRatesCommandDTO
from financial_data.application.errors import ExchangeRateNotFoundError
from financial_data.application.ports.market_data_repository import MarketDataRepository
from financial_data.application.ports.rate_provider import FxRateProvider

_CHILE_TZ = ZoneInfo("America/Santiago")


@dataclass(slots=True)
class GetExchangeRateValue:
    """Return the CLP value for a currency on a given date.

    Resolution order:
    1. Exact date in the database.
    2. Exact date from the external provider chain (result is persisted).
    3. For past/today requests: nearest prior date available in the database.
    4. Not found → ExchangeRateNotFoundError.
    """

    repository: MarketDataRepository
    provider: FxRateProvider

    async def execute(self, currency_code: str, rate_date: date) -> Decimal:
        """Return the exchange rate value using the four-step resolution order."""
        # 1. Exact DB hit.
        value = await self.repository.get_exchange_rate_value(currency_code, rate_date)
        if value is not None:
            return value

        # 2. External provider (exact date only — no carry-forward).
        entry = await self.provider.fetch_rate_entry(currency_code, rate_date)
        if entry is not None:
            await self.repository.refresh_rates(
                RefreshRatesCommandDTO(exchange_rates=[entry])
            )
            return entry.value_clp

        # 3. Nearest prior date in DB — only for past/today requests so future
        #    dates never silently return stale values.
        today = datetime.now(tz=_CHILE_TZ).date()
        if rate_date <= today:
            fallback = await self.repository.get_latest_exchange_rate_value_before(
                currency_code, rate_date
            )
            if fallback is not None:
                return fallback

        raise ExchangeRateNotFoundError(
            f"Exchange rate {currency_code} on {rate_date} not found."
        )
