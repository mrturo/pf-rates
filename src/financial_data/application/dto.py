"""Application DTOs for financial reference data."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CurrencyDTO:
    """Represent Currency DTO."""

    code: str
    name: str
    is_fiat: bool
    unit_kind: str


@dataclass(frozen=True, slots=True)
class ExchangeRateDTO:
    """Represent Exchange Rate DTO."""

    currency_code: str
    rate_date: date
    value_clp: Decimal
    source: str


@dataclass(frozen=True, slots=True)
class ExchangeRateWriteDTO:
    """Represent Exchange Rate Write DTO."""

    currency_code: str
    rate_date: date
    value_clp: Decimal
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class EconomicIndexDTO:
    """Represent Economic Index DTO."""

    code: str
    period_year: int
    period_month: int
    index_value: Decimal
    monthly_change: Decimal | None
    yearly_change: Decimal | None
    base_period: str
    source: str


@dataclass(frozen=True, slots=True)
class EconomicIndexWriteDTO:
    """Represent Economic Index Write DTO."""

    code: str
    period_year: int
    period_month: int
    index_value: Decimal
    monthly_change: Decimal | None = None
    yearly_change: Decimal | None = None
    base_period: str = "DIC-2018"
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class IncomeTaxBracketDTO:
    """Represent Income Tax Bracket DTO."""

    valid_from: date
    valid_to: date | None
    lower_bound_utm: Decimal
    upper_bound_utm: Decimal | None
    marginal_rate: Decimal
    rebate_utm: Decimal


@dataclass(frozen=True, slots=True)
class IncomeTaxBracketWriteDTO:
    """Represent Income Tax Bracket Write DTO."""

    valid_from: date
    valid_to: date | None
    lower_bound_utm: Decimal
    upper_bound_utm: Decimal | None
    marginal_rate: Decimal
    rebate_utm: Decimal


@dataclass(frozen=True, slots=True)
class ProviderExchangeRateRequestDTO:
    """Represent Provider Exchange Rate Request DTO."""

    currency_code: str
    rate_date: date


@dataclass(frozen=True, slots=True)
class ProviderEconomicIndexRequestDTO:
    """Represent Provider Economic Index Request DTO."""

    code: str
    period_year: int
    period_month: int


@dataclass(frozen=True, slots=True)
class RefreshRatesCommandDTO:
    """Represent Refresh Rates Command DTO."""

    exchange_rates: list[ExchangeRateWriteDTO] = field(default_factory=list)
    economic_indices: list[EconomicIndexWriteDTO] = field(default_factory=list)
    provider_exchange_rates: list[ProviderExchangeRateRequestDTO] = field(
        default_factory=list
    )
    provider_economic_indices: list[ProviderEconomicIndexRequestDTO] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class RefreshRatesResultDTO:
    """Represent Refresh Rates Result DTO."""

    upserted_exchange_rates: int
    upserted_economic_indices: int


@dataclass(frozen=True, slots=True)
class SyncRecentMarketDataResultDTO:
    """Represent Sync Recent Market Data Result DTO."""

    requested_exchange_rates: int
    requested_economic_indices: int
    upserted_exchange_rates: int
    upserted_economic_indices: int


@dataclass(frozen=True, slots=True)
class MarketDataSyncRequestDTO:
    """Represent an explicit market-data synchronization request."""

    exchange_rate_dates: dict[str, list[date]] = field(default_factory=dict)
    economic_index_periods: dict[str, list[tuple[int, int]]] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class RefreshIncomeTaxBracketsCommandDTO:
    """Represent Refresh Income Tax Brackets Command DTO."""

    year: int


@dataclass(frozen=True, slots=True)
class RefreshIncomeTaxBracketsResultDTO:
    """Represent Refresh Income Tax Brackets Result DTO."""

    year: int
    refreshed_months: int
    upserted_brackets: int
