"""SQLAlchemy repository for currencies and income tax brackets."""

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from financial_data.application.dto import (
    CurrencyDTO,
    IncomeTaxBracketDTO,
    IncomeTaxBracketWriteDTO,
)
from financial_data.infrastructure.db.models.financial_data import (
    CurrencyModel,
    IncomeTaxBracketModel,
)


class SqlAlchemyReferenceDataRepository:
    """SQLAlchemy-backed reference data repository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the instance."""
        self._session = session

    async def list_currencies(self) -> list[CurrencyDTO]:
        """List all supported currencies."""
        result = await self._session.execute(
            select(CurrencyModel).order_by(CurrencyModel.code)
        )
        return [
            CurrencyDTO(
                code=row.code.strip(),
                name=row.name,
                is_fiat=row.is_fiat,
                unit_kind=row.unit_kind,
            )
            for row in result.scalars().all()
        ]

    async def list_income_tax_brackets(
        self, year: int | None = None
    ) -> list[IncomeTaxBracketDTO]:
        """List income tax brackets, optionally filtered by valid_from year."""
        statement = select(IncomeTaxBracketModel).order_by(
            IncomeTaxBracketModel.valid_from.desc(),
            IncomeTaxBracketModel.lower_bound_utm,
        )
        if year is not None:
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            statement = statement.where(
                IncomeTaxBracketModel.valid_from >= year_start,
                IncomeTaxBracketModel.valid_from <= year_end,
            )
        result = await self._session.execute(statement)
        return [
            IncomeTaxBracketDTO(
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                lower_bound_utm=row.lower_bound_utm,
                upper_bound_utm=row.upper_bound_utm,
                marginal_rate=row.marginal_rate,
                rebate_utm=row.rebate_utm,
            )
            for row in result.scalars().all()
        ]

    async def get_income_tax_bracket(
        self, reference_date: date, taxable_base_utm: Decimal
    ) -> IncomeTaxBracketDTO | None:
        """Return the bracket matching the reference date and taxable base in UTM."""
        result = await self._session.execute(
            select(IncomeTaxBracketModel)
            .where(IncomeTaxBracketModel.valid_from <= reference_date)
            .where(
                or_(
                    IncomeTaxBracketModel.valid_to.is_(None),
                    IncomeTaxBracketModel.valid_to >= reference_date,
                )
            )
            .where(IncomeTaxBracketModel.lower_bound_utm <= taxable_base_utm)
            .where(
                or_(
                    IncomeTaxBracketModel.upper_bound_utm.is_(None),
                    IncomeTaxBracketModel.upper_bound_utm > taxable_base_utm,
                )
            )
            .order_by(
                IncomeTaxBracketModel.valid_from.desc(),
                IncomeTaxBracketModel.lower_bound_utm.desc(),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return IncomeTaxBracketDTO(
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            lower_bound_utm=row.lower_bound_utm,
            upper_bound_utm=row.upper_bound_utm,
            marginal_rate=row.marginal_rate,
            rebate_utm=row.rebate_utm,
        )

    async def upsert_income_tax_brackets(
        self, brackets: list[IncomeTaxBracketWriteDTO]
    ) -> int:
        """Upsert brackets and return the count of rows processed."""
        if not brackets:
            return 0

        statement = insert(IncomeTaxBracketModel).values(
            [
                {
                    "valid_from": item.valid_from,
                    "valid_to": item.valid_to,
                    "lower_bound_utm": item.lower_bound_utm,
                    "upper_bound_utm": item.upper_bound_utm,
                    "marginal_rate": item.marginal_rate,
                    "rebate_utm": item.rebate_utm,
                }
                for item in brackets
            ]
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    IncomeTaxBracketModel.valid_from,
                    IncomeTaxBracketModel.lower_bound_utm,
                ],
                set_={
                    "valid_to": statement.excluded.valid_to,
                    "upper_bound_utm": statement.excluded.upper_bound_utm,
                    "marginal_rate": statement.excluded.marginal_rate,
                    "rebate_utm": statement.excluded.rebate_utm,
                },
            )
        )
        await self._session.commit()
        return len(brackets)
