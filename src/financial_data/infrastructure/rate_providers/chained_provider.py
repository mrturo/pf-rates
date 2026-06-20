"""Fallback chains for market-data providers."""

from datetime import date
from decimal import Decimal
from collections.abc import Awaitable, Callable, Hashable

import structlog

from financial_data.application.dto import EconomicIndexWriteDTO, ExchangeRateWriteDTO
from financial_data.application.ports.rate_provider import (
    EconomicIndexProvider,
    FxRateProvider,
)

log = structlog.get_logger(__name__)


def _provider_name(provider: object) -> str:
    """Get a provider name for logs and source fields."""
    return getattr(provider, "name", provider.__class__.__name__.lower())


def _log_provider_failure(provider: object, exc: Exception) -> None:
    """Log a provider failure."""
    log.warning("provider_failed", provider=_provider_name(provider), error=str(exc))


async def _fetch_first_match[P, TEntry](
    providers: list[P],
    fetcher: Callable[[P], Awaitable[TEntry | None]],
) -> tuple[P, TEntry] | None:
    """Fetch the first non-empty value from the fallback providers."""
    for provider in providers:
        try:
            value = await fetcher(provider)
        except Exception as exc:
            _log_provider_failure(provider, exc)
            continue
        if value is not None:
            return provider, value
    return None


async def _fetch_remaining_entries[P, TKey: Hashable, TEntry](
    providers: list[P],
    requested_items: list[TKey],
    fetcher: Callable[[P, list[TKey]], Awaitable[list[TEntry]]],
    key_fn: Callable[[TEntry], TKey],
) -> list[TEntry]:
    """Fetch entries while keeping the original request order."""
    remaining_items = list(dict.fromkeys(requested_items))
    entries_by_key: dict[TKey, TEntry] = {}
    for provider in providers:
        if not remaining_items:
            break
        try:
            entries = await fetcher(provider, remaining_items)
        except Exception as exc:
            _log_provider_failure(provider, exc)
            continue
        provided_keys = {key_fn(entry) for entry in entries}
        entries_by_key.update({key_fn(entry): entry for entry in entries})
        remaining_items = [
            requested_item
            for requested_item in remaining_items
            if requested_item not in provided_keys
        ]
    return [
        entries_by_key[requested_item]
        for requested_item in requested_items
        if requested_item in entries_by_key
    ]


class ChainedFxProvider:
    """Provide chained fx provider."""

    name = "chained"

    def __init__(self, providers: list[FxRateProvider]) -> None:
        """Initialize the instance."""
        self._providers = providers

    async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
        """Handle fetch rate."""
        entry = await self.fetch_rate_entry(currency_code, on)
        return None if entry is None else entry.value_clp

    async def fetch_rate_entry(
        self, currency_code: str, on: date
    ) -> ExchangeRateWriteDTO | None:
        """Handle fetch rate entry."""
        match = await _fetch_first_match(
            self._providers, lambda provider: provider.fetch_rate(currency_code, on)
        )
        if match is not None:
            provider, value = match
            return ExchangeRateWriteDTO(
                currency_code=currency_code,
                rate_date=on,
                value_clp=value,
                source=_provider_name(provider),
            )
        return None

    async def fetch_rate_entries(
        self, currency_code: str, requested_dates: list[date]
    ) -> list[ExchangeRateWriteDTO]:
        """Handle fetch rate entries."""
        return await _fetch_remaining_entries(
            self._providers,
            requested_dates,
            lambda provider, remaining_dates: provider.fetch_rate_entries(
                currency_code, remaining_dates
            ),
            lambda entry: entry.rate_date,
        )


class ChainedEconomicIndexProvider:
    """Provide chained economic index provider."""

    name = "chained"

    def __init__(self, providers: list[EconomicIndexProvider]) -> None:
        """Initialize the instance."""
        self._providers = providers

    async def fetch_index(
        self, code: str, period_year: int, period_month: int
    ) -> EconomicIndexWriteDTO | None:
        """Handle fetch index."""
        match = await _fetch_first_match(
            self._providers,
            lambda provider: provider.fetch_index(code, period_year, period_month),
        )
        if match is not None:
            _, value = match
            return value
        return None

    async def fetch_indices(
        self, code: str, requested_periods: list[tuple[int, int]]
    ) -> list[EconomicIndexWriteDTO]:
        """Handle fetch indices."""
        return await _fetch_remaining_entries(
            self._providers,
            requested_periods,
            lambda provider, remaining_periods: provider.fetch_indices(
                code, remaining_periods
            ),
            lambda entry: (entry.period_year, entry.period_month),
        )
