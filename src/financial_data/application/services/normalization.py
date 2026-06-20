"""Helpers for normalizing market-data lookup parameters."""

from datetime import date

from financial_data.shared.constants import MONTHLY_EXCHANGE_RATE_CODES


def normalize_exchange_rate_lookup_date(currency_code: str, rate_date: date) -> date:
    """Normalize lookup dates for monthly exchange-rate series.

    Monthly series (e.g. UTM) use the first day of the month as the canonical key.
    Daily series are returned unchanged.
    """
    if currency_code.upper() in MONTHLY_EXCHANGE_RATE_CODES:
        return date(rate_date.year, rate_date.month, 1)
    return rate_date
