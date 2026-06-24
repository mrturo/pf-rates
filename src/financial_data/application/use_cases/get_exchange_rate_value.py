"""Use case for retrieving an exchange rate value with external provider fallback."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from financial_data.application.dto import RefreshRatesCommandDTO
from financial_data.application.errors import ExchangeRateNotFoundError
from financial_data.application.ports.market_data_repository import MarketDataRepository
from financial_data.application.ports.rate_provider import FxRateProvider

_CHILE_TZ = ZoneInfo("America/Santiago")

# Maximum number of prior calendar days to probe the provider when neither the
# exact date nor any prior date exists in the database.
_MAX_PROVIDER_LOOKBACK_DAYS = 7


@dataclass(slots=True)
class GetExchangeRateValue:
    """Return the CLP value for a currency on a given date.

    Resolution order (past/today only for steps 3 and 4):
    1. Exact date in the database.
    2. Exact date from the external provider chain (result is persisted).
    3. Nearest prior date available in the database (not persisted).
    4. Provider probed for each of the preceding _MAX_PROVIDER_LOOKBACK_DAYS days
       (first hit is persisted under the found date and returned).
    5. Not found → ExchangeRateNotFoundError.
    """

    repository: MarketDataRepository
    provider: FxRateProvider

    async def execute(self, currency_code: str, rate_date: date) -> Decimal:
        """Return the exchange rate value using the five-step resolution order."""
        # 1. Exact DB hit.
        value = await self.repository.get_exchange_rate_value(currency_code, rate_date)
        if value is not None:
            return value

        # 2. Provider — exact date only (no carry-forward).
        entry = await self.provider.fetch_rate_entry(currency_code, rate_date)
        if entry is not None:
            await self.repository.refresh_rates(
                RefreshRatesCommandDTO(exchange_rates=[entry])
            )
            return entry.value_clp

        # Steps 3 and 4 apply only to past/today — future dates always 404 here.
        today = datetime.now(tz=_CHILE_TZ).date()
        if rate_date <= today:
            # 3. Nearest prior date in the database within the lookback window
            #    (returned as-is, not persisted).
            window_start = rate_date - timedelta(days=_MAX_PROVIDER_LOOKBACK_DAYS)
            fallback = await self.repository.get_latest_exchange_rate_value_before(
                currency_code, rate_date, on_or_after=window_start
            )
            if fallback is not None:
                return fallback

            # 4. Provider probed for each prior day up to the lookback limit.
            #    Each iteration uses an exact-published value (no carry-forward),
            #    so saving under the found date is safe.
            for days_back in range(1, _MAX_PROVIDER_LOOKBACK_DAYS + 1):
                prior_date = rate_date - timedelta(days=days_back)
                prior_entry = await self.provider.fetch_rate_entry(
                    currency_code, prior_date
                )
                if prior_entry is not None:
                    await self.repository.refresh_rates(
                        RefreshRatesCommandDTO(exchange_rates=[prior_entry])
                    )
                    return prior_entry.value_clp

        raise ExchangeRateNotFoundError(
            f"Exchange rate {currency_code} on {rate_date} not found."
        )
