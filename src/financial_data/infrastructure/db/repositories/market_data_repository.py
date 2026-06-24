"""SQLAlchemy repository for exchange rates and economic indices."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from financial_data.application.errors import FinancialDataValidationError
from financial_data.application.dto import (
    EconomicIndexDTO,
    ExchangeRateDTO,
    RefreshRatesCommandDTO,
    RefreshRatesResultDTO,
)
from financial_data.application.services.normalization import (
    normalize_exchange_rate_lookup_date,
)
from financial_data.infrastructure.db.models.financial_data import (
    CurrencyModel,
    EconomicIndexModel,
    ExchangeRateModel,
)


class SqlAlchemyMarketDataRepository:
    """SQLAlchemy-backed market data repository."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the instance."""
        self._session = session

    async def list_exchange_rates(
        self, currency_code: str | None = None
    ) -> list[ExchangeRateDTO]:
        """List exchange rates."""
        statement = select(ExchangeRateModel).order_by(
            ExchangeRateModel.rate_date.desc(), ExchangeRateModel.currency_code
        )
        if currency_code is not None:
            statement = statement.where(
                ExchangeRateModel.currency_code == currency_code
            )
        result = await self._session.execute(statement)
        return [
            ExchangeRateDTO(
                currency_code=row.currency_code.strip(),
                rate_date=row.rate_date,
                value_clp=row.value_clp,
                source=row.source,
            )
            for row in result.scalars().all()
        ]

    async def list_economic_indices(
        self, code: str | None = None
    ) -> list[EconomicIndexDTO]:
        """List economic indices."""
        statement = select(EconomicIndexModel).order_by(
            EconomicIndexModel.code,
            EconomicIndexModel.period_year.desc(),
            EconomicIndexModel.period_month.desc(),
        )
        if code is not None:
            statement = statement.where(EconomicIndexModel.code == code)
        result = await self._session.execute(statement)
        return [
            EconomicIndexDTO(
                code=row.code,
                period_year=row.period_year,
                period_month=row.period_month,
                index_value=row.index_value,
                monthly_change=row.monthly_change,
                yearly_change=row.yearly_change,
                base_period=row.base_period,
                source=row.source,
            )
            for row in result.scalars().all()
        ]

    async def get_exchange_rate_value(self, code: str, on: date) -> Decimal | None:
        """Get exchange rate value."""
        normalized_date = normalize_exchange_rate_lookup_date(code, on)
        result = await self._session.execute(
            select(ExchangeRateModel.value_clp).where(
                ExchangeRateModel.currency_code == code,
                ExchangeRateModel.rate_date == normalized_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_exchange_rate_value_before(
        self, code: str, before: date, on_or_after: date | None = None
    ) -> Decimal | None:
        """Return the CLP value for the most recent rate strictly before *before*.

        When *on_or_after* is given the search is restricted to that window.
        """
        conditions = [
            ExchangeRateModel.currency_code == code,
            ExchangeRateModel.rate_date < before,
        ]
        if on_or_after is not None:
            conditions.append(ExchangeRateModel.rate_date >= on_or_after)
        result = await self._session.execute(
            select(ExchangeRateModel.value_clp)
            .where(*conditions)
            .order_by(ExchangeRateModel.rate_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_exchange_rate_dates(
        self, code: str, start: date, end: date
    ) -> list[date]:
        """List stored exchange-rate dates for a currency within [start, end]."""
        result = await self._session.execute(
            select(ExchangeRateModel.rate_date).where(
                ExchangeRateModel.currency_code == code,
                ExchangeRateModel.rate_date >= start,
                ExchangeRateModel.rate_date <= end,
            )
        )
        return list(result.scalars().all())

    async def list_unconfirmed_rate_dates(
        self, code: str, start: date, end: date
    ) -> list[date]:
        """Return dates where the rate was fetched on or before its rate_date.

        The comparison uses Chile's timezone (America/Santiago).
        created_at is updated on every upsert, so after a re-fetch on day D+1
        the row is no longer unconfirmed and stabilises naturally.
        """
        result = await self._session.execute(
            select(ExchangeRateModel.rate_date).where(
                ExchangeRateModel.currency_code == code,
                ExchangeRateModel.rate_date >= start,
                ExchangeRateModel.rate_date <= end,
                func.timezone("America/Santiago", ExchangeRateModel.created_at).cast(
                    Date
                )
                <= ExchangeRateModel.rate_date,
            )
        )
        return list(result.scalars().all())

    async def get_economic_index_value(
        self, code: str, year: int, month: int
    ) -> Decimal | None:
        """Get economic index value."""
        result = await self._session.execute(
            select(EconomicIndexModel.index_value).where(
                EconomicIndexModel.code == code,
                EconomicIndexModel.period_year == year,
                EconomicIndexModel.period_month == month,
            )
        )
        return result.scalar_one_or_none()

    async def list_economic_index_periods(
        self, code: str, ranges: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """Return (year, month) pairs from *ranges* that exist in the DB."""
        if not ranges:
            return []
        result = await self._session.execute(
            select(
                EconomicIndexModel.period_year,
                EconomicIndexModel.period_month,
            ).where(
                EconomicIndexModel.code == code,
                tuple_(
                    EconomicIndexModel.period_year,
                    EconomicIndexModel.period_month,
                ).in_(ranges),
            )
        )
        return [(row[0], row[1]) for row in result.all()]

    async def refresh_rates(
        self, command: RefreshRatesCommandDTO
    ) -> RefreshRatesResultDTO:
        """Upsert exchange rates and economic indices."""
        if command.exchange_rates:
            currency_result = await self._session.execute(
                select(CurrencyModel.code).where(
                    CurrencyModel.code.in_(
                        {entry.currency_code for entry in command.exchange_rates}
                    )
                )
            )
            known_currencies = {
                code.strip() for code in currency_result.scalars().all()
            }
            missing_currencies = sorted(
                {entry.currency_code for entry in command.exchange_rates}
                - known_currencies
            )
            if missing_currencies:
                raise FinancialDataValidationError(
                    "Unknown currencies in exchange rates: "
                    f"{', '.join(missing_currencies)}"
                )

            exchange_rate_insert = insert(ExchangeRateModel)
            await self._session.execute(
                exchange_rate_insert.values(
                    [
                        {
                            "currency_code": entry.currency_code,
                            "rate_date": entry.rate_date,
                            "value_clp": entry.value_clp,
                            "source": entry.source,
                        }
                        for entry in command.exchange_rates
                    ]
                ).on_conflict_do_update(
                    index_elements=[
                        ExchangeRateModel.currency_code,
                        ExchangeRateModel.rate_date,
                    ],
                    set_={
                        "value_clp": exchange_rate_insert.excluded.value_clp,
                        "source": exchange_rate_insert.excluded.source,
                        # Refresh the timestamp so that after a re-fetch on day D+1
                        # the row is no longer flagged as same-day by
                        # list_same_day_fetched_dates and stabilises naturally.
                        "created_at": func.now(),
                    },
                )
            )

        if command.economic_indices:
            economic_index_insert = insert(EconomicIndexModel)
            await self._session.execute(
                economic_index_insert.values(
                    [
                        {
                            "code": entry.code,
                            "period_year": entry.period_year,
                            "period_month": entry.period_month,
                            "index_value": entry.index_value,
                            "monthly_change": entry.monthly_change,
                            "yearly_change": entry.yearly_change,
                            "base_period": entry.base_period,
                            "source": entry.source,
                        }
                        for entry in command.economic_indices
                    ]
                ).on_conflict_do_update(
                    index_elements=[
                        EconomicIndexModel.code,
                        EconomicIndexModel.period_year,
                        EconomicIndexModel.period_month,
                    ],
                    set_={
                        "index_value": economic_index_insert.excluded.index_value,
                        "monthly_change": economic_index_insert.excluded.monthly_change,
                        "yearly_change": economic_index_insert.excluded.yearly_change,
                        "base_period": economic_index_insert.excluded.base_period,
                        "source": economic_index_insert.excluded.source,
                    },
                )
            )

        await self._session.commit()
        return RefreshRatesResultDTO(
            upserted_exchange_rates=len(command.exchange_rates),
            upserted_economic_indices=len(command.economic_indices),
        )
