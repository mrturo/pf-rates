"""FastAPI dependency wiring."""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from financial_data.application.ports.market_data_repository import MarketDataRepository
from financial_data.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from financial_data.application.use_cases.refresh_rates import RefreshRates
from financial_data.application.use_cases.refresh_income_tax_brackets import (
    RefreshIncomeTaxBrackets,
)
from financial_data.application.use_cases.sync_recent_market_data import (
    SyncRecentMarketData,
)
from financial_data.config import settings
from financial_data.infrastructure.db.repositories.market_data_repository import (
    SqlAlchemyMarketDataRepository,
)
from financial_data.infrastructure.db.repositories.reference_data_repository import (
    SqlAlchemyReferenceDataRepository,
)
from financial_data.infrastructure.db.session import SessionLocal
from financial_data.infrastructure.rate_providers.chained_provider import (
    ChainedEconomicIndexProvider,
    ChainedFxProvider,
)
from financial_data.infrastructure.rate_providers.official_providers import (
    BcchSeriesProvider,
    MindicadorRateProvider,
    SiiIncomeTaxBracketProvider,
    SiiIndicatorsProvider,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a database session."""
    async with SessionLocal() as session:
        yield session


def get_market_data_repository(
    session: AsyncSession = Depends(get_session),
) -> MarketDataRepository:
    """Get market data repository."""
    return SqlAlchemyMarketDataRepository(session)


def get_reference_data_repository(
    session: AsyncSession = Depends(get_session),
) -> ReferenceDataRepository:
    """Get reference data repository."""
    return SqlAlchemyReferenceDataRepository(session)


def get_fx_rate_provider() -> ChainedFxProvider:
    """Build the chained FX rate provider."""
    bcch = BcchSeriesProvider(
        user=settings.bcch_api_user,
        password=settings.bcch_api_password,
        series_codes={
            "UF": settings.bcch_series_uf,
            "USD": settings.bcch_series_usd,
            "EUR": settings.bcch_series_eur,
            "UTM": settings.bcch_series_utm,
        },
        base_url=settings.bcch_api_base_url,
        timeout_seconds=settings.rate_provider_timeout_seconds,
    )
    return ChainedFxProvider(
        [
            bcch,
            SiiIndicatorsProvider(
                base_url=settings.sii_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
            ),
            MindicadorRateProvider(
                base_url=settings.mindicador_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
            ),
        ]
    )


def get_economic_index_provider() -> ChainedEconomicIndexProvider:
    """Build the chained economic-index provider."""
    return ChainedEconomicIndexProvider(
        [
            BcchSeriesProvider(
                user=settings.bcch_api_user,
                password=settings.bcch_api_password,
                series_codes={"IPC_CL": settings.bcch_series_ipc_cl},
                base_url=settings.bcch_api_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
            ),
            SiiIndicatorsProvider(
                base_url=settings.sii_base_url,
                timeout_seconds=settings.rate_provider_timeout_seconds,
            ),
        ]
    )


def get_income_tax_bracket_provider() -> SiiIncomeTaxBracketProvider:
    """Build the income tax bracket provider."""
    return SiiIncomeTaxBracketProvider(
        base_url=settings.sii_base_url,
        timeout_seconds=settings.rate_provider_timeout_seconds,
    )


def get_refresh_rates_use_case(
    repository: MarketDataRepository = Depends(get_market_data_repository),
) -> RefreshRates:
    """Build the RefreshRates use case."""
    return RefreshRates(
        repository,
        get_fx_rate_provider(),
        get_economic_index_provider(),
    )


def get_refresh_income_tax_brackets_use_case(
    repository: ReferenceDataRepository = Depends(get_reference_data_repository),
) -> RefreshIncomeTaxBrackets:
    """Build the RefreshIncomeTaxBrackets use case."""
    return RefreshIncomeTaxBrackets(repository, get_income_tax_bracket_provider())


def build_sync_use_case(session: AsyncSession) -> SyncRecentMarketData:
    """Build the SyncRecentMarketData use case directly from a session."""
    return SyncRecentMarketData(
        SqlAlchemyMarketDataRepository(session),
        get_fx_rate_provider(),
        get_economic_index_provider(),
    )


def get_sync_use_case(
    session: AsyncSession = Depends(get_session),
) -> SyncRecentMarketData:
    """Build the SyncRecentMarketData use case as a FastAPI dependency."""
    return build_sync_use_case(session)
