"""Port definition for reference-data persistence."""

from datetime import date
from decimal import Decimal
from typing import Protocol

from financial_data.application.dto import (
    CurrencyDTO,
    IncomeTaxBracketDTO,
    IncomeTaxBracketWriteDTO,
)


class ReferenceDataRepository(Protocol):
    """Persistence port for currencies and income tax brackets."""

    async def list_currencies(self) -> list[CurrencyDTO]:
        """List all supported currencies."""
        ...

    async def list_income_tax_brackets(
        self, year: int | None = None
    ) -> list[IncomeTaxBracketDTO]:
        """List income tax brackets, optionally filtered by valid_from year."""
        ...

    async def get_income_tax_bracket(
        self, payment_date: date, taxable_base_utm: Decimal
    ) -> IncomeTaxBracketDTO | None:
        """Return the bracket that matches the payment date and taxable base."""
        ...

    async def upsert_income_tax_brackets(
        self, brackets: list[IncomeTaxBracketWriteDTO]
    ) -> int:
        """Upsert brackets and return the count of rows processed."""
        ...
