"""Market-data sync route."""

from fastapi import APIRouter, Depends

from financial_data.application.use_cases.sync_recent_market_data import (
    SyncRecentMarketData,
)
from financial_data.interfaces.api.dependencies import get_sync_use_case

router = APIRouter(tags=["sync"])


@router.post("/sync")
async def sync_market_data(
    use_case: SyncRecentMarketData = Depends(get_sync_use_case),
) -> dict[str, int]:
    """Trigger a rolling 365-day / 12-month sync of all missing market data."""
    result = await use_case.execute()
    return {
        "exchange_rates_upserted": result.upserted_exchange_rates,
        "economic_indices_upserted": result.upserted_economic_indices,
    }
