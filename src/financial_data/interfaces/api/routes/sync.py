"""Market-data sync route."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from financial_data.application.use_cases.sync_recent_market_data import (
    SyncRecentMarketData,
)
from financial_data.interfaces.api.dependencies import get_sync_use_case

router = APIRouter(tags=["sync"])


class SyncRequest(BaseModel):
    """Optional window overrides for the sync operation."""

    lookback_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Rolling lookback window in days (default: 365).",
    )
    forward_days: int | None = Field(
        default=None,
        ge=0,
        le=365,
        description=(
            "Forward window for currencies with pre-published values, e.g. UF "
            "(default: 35)."
        ),
    )


@router.post("/sync")
async def sync_market_data(
    payload: SyncRequest = SyncRequest(),
    use_case: SyncRecentMarketData = Depends(get_sync_use_case),
) -> dict[str, int]:
    """Trigger a rolling sync of all missing market data.

    Omit the body (or send `{}`) to use the default 365-day lookback and
    35-day UF forward window.
    """
    result = await use_case.execute(
        lookback_days=payload.lookback_days,
        forward_days=payload.forward_days,
    )
    return {
        "exchange_rates_upserted": result.upserted_exchange_rates,
        "economic_indices_upserted": result.upserted_economic_indices,
        "brackets_upserted": result.upserted_brackets,
    }
