"""Quantization helpers for Chilean financial amounts.

These helpers are exported for use by the pf-payroll HTTP adapter (Part 2).
"""

from decimal import Decimal

__all__ = ["quantize_clp", "quantize_utm"]

_CLP_QUANT = Decimal("1")
_UTM_QUANT = Decimal("0.000001")


def quantize_clp(value: Decimal) -> Decimal:
    """Quantize a CLP monetary amount to the nearest peso (0 decimal places)."""
    return value.quantize(_CLP_QUANT)


def quantize_utm(value: Decimal) -> Decimal:
    """Quantize a UTM value to six decimal places."""
    return value.quantize(_UTM_QUANT)
