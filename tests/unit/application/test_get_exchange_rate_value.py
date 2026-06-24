"""Tests for the GetExchangeRateValue use case."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from financial_data.application.dto import (
    ExchangeRateWriteDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)
from financial_data.application.errors import ExchangeRateNotFoundError
from financial_data.application.use_cases.get_exchange_rate_value import (
    GetExchangeRateValue,
)

# A clearly-past date that will never equal today in any timezone.
_PAST = date(2024, 6, 1)
# A clearly-future date.
_FUTURE = date(2099, 12, 31)


class _StubRepository:
    """Minimal MarketDataRepository test double."""

    def __init__(
        self,
        db_value: Decimal | None = None,
        fallback_value: Decimal | None = None,
    ) -> None:
        self._db_value = db_value
        self._fallback_value = fallback_value
        self.saved_command: RefreshRatesCommandDTO | None = None

    async def get_exchange_rate_value(
        self, currency_code: str, rate_date: date
    ) -> Decimal | None:
        """Return preconfigured DB value."""
        return self._db_value

    async def get_latest_exchange_rate_value_before(
        self, code: str, before: date
    ) -> Decimal | None:
        """Return preconfigured fallback value."""
        return self._fallback_value

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Record the command that was saved."""
        self.saved_command = command
        return RefreshRatesResultDTO(
            upserted_exchange_rates=len(command.exchange_rates),
            upserted_economic_indices=0,
        )


class _StubProvider:
    """Minimal FxRateProvider test double."""

    def __init__(self, entry: ExchangeRateWriteDTO | None = None) -> None:
        self._entry = entry

    async def fetch_rate_entry(
        self, currency_code: str, on: date
    ) -> ExchangeRateWriteDTO | None:
        """Return preconfigured provider entry."""
        return self._entry


async def test_returns_db_value_when_present() -> None:
    """Returns the DB value without calling the provider."""
    repo = _StubRepository(db_value=Decimal("980.50"))
    provider = _StubProvider(entry=None)
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("980.50")
    assert repo.saved_command is None  # provider path not taken


async def test_saves_and_returns_provider_value_on_db_miss() -> None:
    """Persists the provider entry and returns its value on a DB miss."""
    entry = ExchangeRateWriteDTO(
        currency_code="USD",
        rate_date=_PAST,
        value_clp=Decimal("980.50"),
        source="mindicador",
    )
    repo = _StubRepository(db_value=None)
    provider = _StubProvider(entry=entry)
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("980.50")
    assert repo.saved_command is not None
    assert repo.saved_command.exchange_rates == [entry]


async def test_returns_nearest_prior_db_value_when_provider_misses() -> None:
    """Returns the nearest prior DB rate when neither exact DB nor provider has it.

    The fallback is available for past/today requests only; the result is
    NOT persisted under the requested date.
    """
    repo = _StubRepository(db_value=None, fallback_value=Decimal("975.00"))
    provider = _StubProvider(entry=None)
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("975.00")
    assert repo.saved_command is None  # fallback value must not be stored


async def test_raises_not_found_when_db_provider_and_fallback_all_miss() -> None:
    """Raises ExchangeRateNotFoundError when no source has the rate."""
    repo = _StubRepository(db_value=None, fallback_value=None)
    provider = _StubProvider(entry=None)
    use_case = GetExchangeRateValue(repo, provider)

    with pytest.raises(ExchangeRateNotFoundError):
        await use_case.execute("USD", _PAST)


async def test_raises_not_found_for_future_date_even_when_fallback_exists() -> None:
    """Future dates skip the DB fallback and raise 404 immediately.

    This prevents a future date from silently returning a stale rate from a
    completely different date.
    """
    repo = _StubRepository(db_value=None, fallback_value=Decimal("975.00"))
    provider = _StubProvider(entry=None)
    use_case = GetExchangeRateValue(repo, provider)

    # Patch "today" in Chile time to a date clearly in the past so _FUTURE stays future.
    with patch(
        "financial_data.application.use_cases.get_exchange_rate_value.datetime"
    ) as mock_dt:
        mock_dt.now.return_value.date.return_value = _PAST
        with pytest.raises(ExchangeRateNotFoundError):
            await use_case.execute("USD", _FUTURE)

    assert repo.saved_command is None
