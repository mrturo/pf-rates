"""Database session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from financial_data.config import settings

# pool_pre_ping validates each connection before use, recovering from stale
# connections caused by server-side idle timeouts (Neon closes idle connections
# after ~5 min).  pool_recycle proactively replaces connections older than that
# window so the pre-ping path is rarely needed in practice.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
