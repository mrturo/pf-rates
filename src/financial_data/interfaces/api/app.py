"""FastAPI application entrypoint."""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel

from financial_data.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from financial_data.config import settings
from financial_data.infrastructure.db.session import SessionLocal
from financial_data.infrastructure.logging.logger import logger
from financial_data.interfaces.api.dependencies import (
    build_sync_use_case,
    get_reference_data_repository,
)
from financial_data.interfaces.api.routes.exchange_rates import (
    router as exchange_rates_router,
)
from financial_data.interfaces.api.routes.economic_indices import (
    router as economic_indices_router,
)
from financial_data.interfaces.api.routes.income_tax_brackets import (
    router as income_tax_brackets_router,
)
from financial_data.interfaces.api.routes.sync import router as sync_router
from financial_data.interfaces.api.security import verify_api_key

_root_router = APIRouter()


class CurrencyRead(BaseModel):
    """Represent Currency Read."""

    code: str
    name: str
    is_fiat: bool
    unit_kind: str


@_root_router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok", "service": "pf-rates"}


@_root_router.get(
    "/currencies",
    tags=["currencies"],
    response_model=list[CurrencyRead],
    dependencies=[Depends(verify_api_key)],
)
async def list_currencies(
    repository: ReferenceDataRepository = Depends(get_reference_data_repository),
) -> list[CurrencyRead]:
    """List all supported currencies."""
    return [
        CurrencyRead(
            code=item.code,
            name=item.name,
            is_fiat=item.is_fiat,
            unit_kind=item.unit_kind,
        )
        for item in await repository.list_currencies()
    ]


async def _run_startup_sync() -> None:
    """Run a rolling market-data sync at startup (skipped during tests)."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return

    logger.info("startup_market_data_sync_started")
    try:
        async with SessionLocal() as session:
            result = await build_sync_use_case(session).execute()
    except asyncio.CancelledError:
        logger.info("startup_market_data_sync_cancelled")
        raise
    except Exception as exc:
        logger.warning("startup_market_data_sync_skipped", reason=str(exc))
        return

    logger.info(
        "startup_market_data_sync_completed",
        upserted_exchange_rates=result.upserted_exchange_rates,
        upserted_economic_indices=result.upserted_economic_indices,
        upserted_brackets=result.upserted_brackets,
    )


@asynccontextmanager
async def lifespan(application: FastAPI):  # type: ignore[type-arg]
    """Run application lifespan hooks."""
    _parsed = urlparse(settings.database_url)
    logger.info(
        "startup_database_target",
        host=_parsed.hostname,
        port=_parsed.port,
        database=_parsed.path.lstrip("/"),
    )
    sync_task = asyncio.create_task(_run_startup_sync())
    application.state.market_data_sync_task = sync_task
    try:
        yield
    finally:
        if not sync_task.done():
            sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await sync_task


_DESCRIPTION = """
Chilean financial reference data microservice.

Provides exchange rates (USD, EUR), economic indices (UF, UTM, IPC),
and income tax brackets sourced from Mindicador and Banco Central de Chile.
"""

_OPENAPI_TAGS = [
    {"name": "health", "description": "Service liveness check."},
    {"name": "currencies", "description": "Supported currency catalogue."},
    {
        "name": "exchange-rates",
        "description": "CLP exchange rates — list, lookup, and refresh.",
    },
    {
        "name": "economic-indices",
        "description": "UF / UTM / IPC indices — list, lookup, and refresh.",
    },
    {
        "name": "income-tax-brackets",
        "description": "Chilean income tax brackets — lookup, list, and refresh.",
    },
    {
        "name": "sync",
        "description": "Trigger a rolling 365-day sync of all missing market data.",
    },
]

app = FastAPI(
    title="pf-rates",
    version="0.1.0",
    description=_DESCRIPTION,
    openapi_tags=_OPENAPI_TAGS,
    lifespan=lifespan,
)
app.include_router(_root_router)
app.include_router(exchange_rates_router, dependencies=[Depends(verify_api_key)])
app.include_router(economic_indices_router, dependencies=[Depends(verify_api_key)])
app.include_router(income_tax_brackets_router, dependencies=[Depends(verify_api_key)])
app.include_router(sync_router, dependencies=[Depends(verify_api_key)])
