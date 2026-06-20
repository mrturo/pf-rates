"""Tests for domain quantization helpers."""

from decimal import Decimal

from financial_data.domain.quantizers import quantize_clp, quantize_utm


def test_quantize_clp_rounds_to_nearest_peso() -> None:
    """quantize_clp rounds to 0 decimal places (nearest whole peso)."""
    assert quantize_clp(Decimal("1234.567")) == Decimal("1235")
    assert quantize_clp(Decimal("100.4")) == Decimal("100")
    assert quantize_clp(Decimal("0")) == Decimal("0")
    assert quantize_clp(Decimal("38000")) == Decimal("38000")


def test_quantize_utm_rounds_to_six_decimal_places() -> None:
    """quantize_utm rounds to 6 decimal places."""
    assert quantize_utm(Decimal("13.1234567")) == Decimal("13.123457")
    assert quantize_utm(Decimal("0")) == Decimal("0.000000")
    assert quantize_utm(Decimal("1")) == Decimal("1.000000")
