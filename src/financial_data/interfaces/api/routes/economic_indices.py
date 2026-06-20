"""Economic-index routes."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from financial_data.application.errors import (
    EconomicIndexNotFoundError,
    FinancialDataError,
)
from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ProviderEconomicIndexRequestDTO,
    RefreshRatesCommandDTO,
)
from financial_data.interfaces.api.routes._refresh_deps import (
    MarketDataRepository,
    RefreshRates,
    get_market_data_repository,
    get_refresh_rates_use_case,
    to_http_exception,
    RefreshRatesResponse,
)

router = APIRouter(prefix="/economic-indices", tags=["economic-indices"])


class EconomicIndexRead(BaseModel):
    """Represent Economic Index Read."""

    code: str
    period_year: int
    period_month: int
    index_value: str
    monthly_change: str | None
    yearly_change: str | None
    base_period: str
    source: str


class EconomicIndexWrite(BaseModel):
    """Represent Economic Index Write."""

    code: str = Field(min_length=1)
    period_year: int = Field(ge=1990, le=2100)
    period_month: int = Field(ge=1, le=12)
    index_value: Decimal = Field(gt=0)
    monthly_change: Decimal | None = None
    yearly_change: Decimal | None = None
    base_period: str = Field(default="DIC-2018", min_length=1)
    source: str = Field(default="manual", min_length=1)


class ProviderEconomicIndexRequest(BaseModel):
    """Represent Provider Economic Index Request."""

    code: str = Field(min_length=1)
    period_year: int = Field(ge=1990, le=2100)
    period_month: int = Field(ge=1, le=12)


class EconomicIndexRefreshRequest(BaseModel):
    """Represent Economic Index Refresh Request."""

    economic_indices: list[EconomicIndexWrite] = Field(default_factory=list)
    fetch_economic_indices: list[ProviderEconomicIndexRequest] = Field(
        default_factory=list
    )


@router.get("", response_model=list[EconomicIndexRead])
async def list_economic_indices(
    code: str | None = Query(default=None),
    repository: MarketDataRepository = Depends(get_market_data_repository),
) -> list[EconomicIndexRead]:
    """List stored economic indices, optionally filtered by code."""
    return [
        EconomicIndexRead(
            code=item.code,
            period_year=item.period_year,
            period_month=item.period_month,
            index_value=str(item.index_value),
            monthly_change=str(item.monthly_change)
            if item.monthly_change is not None
            else None,
            yearly_change=str(item.yearly_change)
            if item.yearly_change is not None
            else None,
            base_period=item.base_period,
            source=item.source,
        )
        for item in await repository.list_economic_indices(code)
    ]


@router.get("/value")
async def get_economic_index_value(
    code: str = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    repository: MarketDataRepository = Depends(get_market_data_repository),
) -> dict[str, str]:
    """Return the index value for the given code and period."""
    value = await repository.get_economic_index_value(code, year, month)
    if value is None:
        raise to_http_exception(
            EconomicIndexNotFoundError(
                f"Economic index {code} for {year:04d}-{month:02d} not found."
            )
        )
    return {"index_value": str(value)}


@router.post("/refresh", response_model=RefreshRatesResponse)
async def refresh_economic_indices(
    payload: EconomicIndexRefreshRequest,
    use_case: RefreshRates = Depends(get_refresh_rates_use_case),
) -> RefreshRatesResponse:
    """Upsert economic indices from manual entries or provider fetches."""
    try:
        result = await use_case.execute(
            RefreshRatesCommandDTO(
                economic_indices=[
                    EconomicIndexWriteDTO(
                        code=item.code,
                        period_year=item.period_year,
                        period_month=item.period_month,
                        index_value=item.index_value,
                        monthly_change=item.monthly_change,
                        yearly_change=item.yearly_change,
                        base_period=item.base_period,
                        source=item.source,
                    )
                    for item in payload.economic_indices
                ],
                provider_economic_indices=[
                    ProviderEconomicIndexRequestDTO(
                        code=item.code,
                        period_year=item.period_year,
                        period_month=item.period_month,
                    )
                    for item in payload.fetch_economic_indices
                ],
            )
        )
    except FinancialDataError as exc:
        raise to_http_exception(exc) from exc
    return RefreshRatesResponse(
        upserted_exchange_rates=result.upserted_exchange_rates,
        upserted_economic_indices=result.upserted_economic_indices,
    )
