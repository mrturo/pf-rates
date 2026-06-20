"""SQLAlchemy ORM models for financial reference data."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from financial_data.infrastructure.db.base import Base


class CurrencyModel(Base):
    """Represent Currency Model."""

    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    is_fiat: Mapped[bool] = mapped_column(Boolean, default=True)
    unit_kind: Mapped[str] = mapped_column(String(20), default="currency")


class ExchangeRateModel(Base):
    """Represent Exchange Rate Model."""

    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    rate_date: Mapped[date] = mapped_column(Date)
    value_clp: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(String(40), default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EconomicIndexModel(Base):
    """Represent Economic Index Model."""

    __tablename__ = "economic_indices"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    period_year: Mapped[int] = mapped_column()
    period_month: Mapped[int] = mapped_column()
    index_value: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    monthly_change: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    yearly_change: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    base_period: Mapped[str] = mapped_column(String(10), default="DIC-2018")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IncomeTaxBracketModel(Base):
    """Represent Income Tax Bracket Model."""

    __tablename__ = "income_tax_brackets"

    id: Mapped[int] = mapped_column(primary_key=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    lower_bound_utm: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    upper_bound_utm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    marginal_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    rebate_utm: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
