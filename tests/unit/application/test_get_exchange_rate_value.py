"""Tests for the GetExchangeRateValue use case."""

from datetime import date, timedelta
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


def _entry(rate_date: date, value: str = "980.50") -> ExchangeRateWriteDTO:
    """Build a minimal ExchangeRateWriteDTO for the given date."""
    return ExchangeRateWriteDTO(
        currency_code="USD",
        rate_date=rate_date,
        value_clp=Decimal(value),
        source="mindicador",
    )


class _StubRepository:
    """Minimal MarketDataRepository test double."""

    def __init__(
        self,
        db_value: Decimal | None = None,
        fallback_value: Decimal | None = None,
    ) -> None:
        self._db_value = db_value
        self._fallback_value = fallback_value
        self.saved_commands: list[RefreshRatesCommandDTO] = []

    async def get_exchange_rate_value(
        self, currency_code: str, rate_date: date
    ) -> Decimal | None:
        """Return preconfigured DB value."""
        return self._db_value

    async def get_latest_exchange_rate_value_before(
        self, code: str, before: date, on_or_after: date | None = None
    ) -> Decimal | None:
        """Return preconfigured fallback value."""
        return self._fallback_value

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Record every save command."""
        self.saved_commands.append(command)
        return RefreshRatesResultDTO(
            upserted_exchange_rates=len(command.exchange_rates),
            upserted_economic_indices=0,
        )

    @property
    def saved_command(self) -> RefreshRatesCommandDTO | None:
        """Return the single save command, or None."""
        return self.saved_commands[0] if self.saved_commands else None


class _StubProvider:
    """Date-keyed FxRateProvider test double.

    Returns an entry only when the requested date is an explicit key in the
    supplied dict, so exact-date misses and prior-day hits can be tested
    independently.
    """

    def __init__(self, entries: dict[date, ExchangeRateWriteDTO] | None = None) -> None:
        self._entries = entries or {}

    async def fetch_rate_entry(
        self, currency_code: str, on: date
    ) -> ExchangeRateWriteDTO | None:
        """Return the entry for *on* if present, else None."""
        return self._entries.get(on)


# ---------------------------------------------------------------------------
# Step 1 — exact DB hit
# ---------------------------------------------------------------------------


async def test_returns_db_value_when_present() -> None:
    """Step 1: returns the DB value without touching the provider."""
    repo = _StubRepository(db_value=Decimal("980.50"))
    provider = _StubProvider()
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("980.50")
    assert repo.saved_command is None


# ---------------------------------------------------------------------------
# Step 2 — provider exact hit
# ---------------------------------------------------------------------------


async def test_saves_and_returns_provider_value_on_db_miss() -> None:
    """Step 2: persists the provider entry and returns its value on a DB miss."""
    entry = _entry(_PAST)
    repo = _StubRepository(db_value=None)
    provider = _StubProvider(entries={_PAST: entry})
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("980.50")
    assert repo.saved_command is not None
    assert repo.saved_command.exchange_rates == [entry]


# ---------------------------------------------------------------------------
# Step 3 — DB nearest prior hit
# ---------------------------------------------------------------------------


async def test_returns_nearest_prior_db_value_when_provider_misses() -> None:
    """Step 3: returns the nearest prior DB rate; result is NOT persisted."""
    repo = _StubRepository(db_value=None, fallback_value=Decimal("975.00"))
    provider = _StubProvider()  # exact date misses
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("975.00")
    assert repo.saved_command is None


# ---------------------------------------------------------------------------
# Step 4 — provider prior-day loop
# ---------------------------------------------------------------------------


async def test_finds_prior_day_in_provider_on_first_attempt() -> None:
    """Step 4 (day-1): provider loop hits on the first prior day."""
    day_minus_1 = _PAST - timedelta(days=1)
    prior_entry = _entry(day_minus_1, "970.00")
    repo = _StubRepository(db_value=None, fallback_value=None)
    provider = _StubProvider(entries={day_minus_1: prior_entry})
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("970.00")
    assert repo.saved_command is not None
    assert repo.saved_command.exchange_rates == [prior_entry]


async def test_finds_prior_day_in_provider_after_several_misses() -> None:
    """Step 4 (day-k>1): provider loop skips empty days before finding a hit."""
    day_minus_3 = _PAST - timedelta(days=3)
    prior_entry = _entry(day_minus_3, "965.00")
    repo = _StubRepository(db_value=None, fallback_value=None)
    # Only day-3 has data; day-1 and day-2 miss.
    provider = _StubProvider(entries={day_minus_3: prior_entry})
    use_case = GetExchangeRateValue(repo, provider)

    result = await use_case.execute("USD", _PAST)

    assert result == Decimal("965.00")
    assert repo.saved_command is not None
    assert repo.saved_command.exchange_rates == [prior_entry]


async def test_raises_not_found_when_all_sources_exhausted() -> None:
    """Step 5: 404 after exhausting DB prior and all provider lookback days."""
    repo = _StubRepository(db_value=None, fallback_value=None)
    provider = _StubProvider()  # nothing for any date
    use_case = GetExchangeRateValue(repo, provider)

    with pytest.raises(ExchangeRateNotFoundError):
        await use_case.execute("USD", _PAST)

    assert repo.saved_command is None


# ---------------------------------------------------------------------------
# Future-date guard
# ---------------------------------------------------------------------------


async def test_future_date_skips_fallback_and_raises_not_found() -> None:
    """Future dates skip steps 3 and 4 entirely and always 404."""
    # Provide a prior-day entry so the test would fail if the loop ran.
    day_minus_1 = _FUTURE - timedelta(days=1)
    repo = _StubRepository(db_value=None, fallback_value=Decimal("975.00"))
    provider = _StubProvider(entries={day_minus_1: _entry(day_minus_1)})
    use_case = GetExchangeRateValue(repo, provider)

    with patch(
        "financial_data.application.use_cases.get_exchange_rate_value.datetime"
    ) as mock_dt:
        mock_dt.now.return_value.date.return_value = _PAST
        with pytest.raises(ExchangeRateNotFoundError):
            await use_case.execute("USD", _FUTURE)

    assert repo.saved_command is None
