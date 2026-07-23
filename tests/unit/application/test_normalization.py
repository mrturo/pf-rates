"""Tests for exchange-rate date normalization."""

from datetime import date

from financial_data.domain.normalization import (
    normalize_exchange_rate_lookup_date,
)


def test_daily_currency_date_is_unchanged() -> None:
    """Daily currencies (USD, EUR, UF) keep their exact date."""
    assert normalize_exchange_rate_lookup_date("USD", date(2026, 1, 15)) == date(
        2026, 1, 15
    )
    assert normalize_exchange_rate_lookup_date("EUR", date(2026, 6, 20)) == date(
        2026, 6, 20
    )
    assert normalize_exchange_rate_lookup_date("UF", date(2026, 3, 31)) == date(
        2026, 3, 31
    )


def test_monthly_currency_date_is_normalized_to_first_of_month() -> None:
    """Monthly currencies (UTM) are normalized to the first day of the month."""
    assert normalize_exchange_rate_lookup_date("UTM", date(2026, 1, 15)) == date(
        2026, 1, 1
    )
    assert normalize_exchange_rate_lookup_date("utm", date(2026, 6, 20)) == date(
        2026, 6, 1
    )
    assert normalize_exchange_rate_lookup_date("UTM", date(2026, 1, 1)) == date(
        2026, 1, 1
    )
