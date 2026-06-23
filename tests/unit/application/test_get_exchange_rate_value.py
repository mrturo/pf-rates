"""Tests for the GetExchangeRateValue use case."""

from datetime import date
from decimal import Decimal

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


class _StubRepository:
    """Minimal MarketDataRepository test double."""

    def __init__(self, db_value: Decimal | None = None) -> None:
        self._db_value = db_value
        self.saved_command: RefreshRatesCommandDTO | None = None

    async def get_exchange_rate_value(
        self, currency_code: str, rate_date: date
    ) -> Decimal | None:
        """Return preconfigured DB value."""
        return self._db_value

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

    result = await use_case.execute("USD", date(2026, 1, 15))

    assert result == Decimal("980.50")
    assert repo.saved_command is None  # provider path not taken


async def test_raises_not_found_when_db_and_provider_both_miss() -> None:
    """Raises ExchangeRateNotFoundError when neither DB nor provider has the rate."""
    repo = _StubRepository(db_value=None)
    provider = _StubProvider(entry=None)
    use_case = GetExchangeRateValue(repo, provider)

    with pytest.raises(ExchangeRateNotFoundError):
        await use_case.execute("USD", date(2026, 1, 15))


async def test_saves_and_returns_provider_value_on_db_miss() -> None:
    """Persists the provider entry and returns its value on a DB miss."""
    entry = ExchangeRateWriteDTO(
        currency_code="USD",
        rate_date=date(2026, 1, 15),
        value_clp=Decimal("980.50"),
        source="mindicador",
    )
    repo = _StubRepository(db_value=None)
    provider = _StubProvider(entry=entry)
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", date(2026, 1, 15))

    assert result == Decimal("980.50")
    assert repo.saved_command is not None
    assert repo.saved_command.exchange_rates == [entry]
