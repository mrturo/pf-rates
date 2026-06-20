"""Shared Pydantic response schemas."""

from pydantic import BaseModel


class RefreshRatesResponse(BaseModel):
    """Shared response for exchange-rate and economic-index refresh endpoints."""

    upserted_exchange_rates: int
    upserted_economic_indices: int
