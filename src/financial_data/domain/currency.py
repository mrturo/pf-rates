"""Currency value object."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Currency:
    """Immutable value object representing a supported currency."""

    code: str
    name: str
    is_fiat: bool
    unit_kind: str
