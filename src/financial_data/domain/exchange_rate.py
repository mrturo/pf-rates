"""Exchange rate value object."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """Immutable value object representing a CLP exchange rate on a given date.

    Invariants:
    - value_clp must be positive (exchange rates are always positive).
    """

    currency_code: str
    rate_date: date
    value_clp: Decimal
    source: str = "manual"

    def __post_init__(self) -> None:
        """Enforce domain invariants."""
        if self.value_clp <= 0:
            raise ValueError(f"value_clp must be positive; got {self.value_clp}")
