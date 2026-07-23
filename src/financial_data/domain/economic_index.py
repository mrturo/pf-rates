"""Economic index value object."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class EconomicIndex:
    """Immutable value object representing an economic index for a monthly period.

    Invariants:
    - period_month must be 1-12.
    - index_value must be positive (index levels are always > 0).
    """

    code: str
    period_year: int
    period_month: int
    index_value: Decimal
    monthly_change: Decimal | None = None
    yearly_change: Decimal | None = None
    base_period: str = "DIC-2018"
    source: str = "manual"

    def __post_init__(self) -> None:
        """Enforce domain invariants."""
        if not (1 <= self.period_month <= 12):
            raise ValueError(
                f"period_month must be between 1 and 12; got {self.period_month}"
            )
        if self.index_value <= 0:
            raise ValueError(f"index_value must be positive; got {self.index_value}")
