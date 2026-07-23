"""Income tax bracket value object."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class IncomeTaxBracket:
    """Immutable value object representing a monthly Chilean income tax bracket.

    Invariants:
    - lower_bound_utm must be >= 0.
    - upper_bound_utm, when present, must be > lower_bound_utm.
    - marginal_rate must be in [0, 1].
    - rebate_utm must be >= 0.
    """

    valid_from: date
    valid_to: date | None
    lower_bound_utm: Decimal
    upper_bound_utm: Decimal | None
    marginal_rate: Decimal
    rebate_utm: Decimal

    def __post_init__(self) -> None:
        """Enforce domain invariants."""
        if self.lower_bound_utm < 0:
            raise ValueError(
                f"lower_bound_utm must be >= 0; got {self.lower_bound_utm}"
            )
        if (
            self.upper_bound_utm is not None
            and self.upper_bound_utm <= self.lower_bound_utm
        ):
            raise ValueError(
                f"upper_bound_utm ({self.upper_bound_utm}) must be greater than "
                f"lower_bound_utm ({self.lower_bound_utm})"
            )
        if not (Decimal("0") <= self.marginal_rate <= Decimal("1")):
            raise ValueError(
                f"marginal_rate must be in [0, 1]; got {self.marginal_rate}"
            )
        if self.rebate_utm < 0:
            raise ValueError(f"rebate_utm must be >= 0; got {self.rebate_utm}")
