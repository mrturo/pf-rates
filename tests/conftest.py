"""Shared test fixtures."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from financial_data.application.dto import SyncRecentMarketDataResultDTO
from financial_data.interfaces.api.app import app
from financial_data.interfaces.api.dependencies import get_session, get_sync_use_case

_ROOT = Path(__file__).parent.parent

# SQLAlchemy connect_args for testcontainers: the ephemeral PostgreSQL does not
# use TLS, so we must disable SSL to avoid asyncpg's SSL-first handshake.
_TC_ENGINE_KWARGS: dict[str, Any] = {"connect_args": {"ssl": False}}


class _StubSyncUseCase:
    """Stub SyncRecentMarketData that makes no network calls."""

    async def execute(
        self,
        lookback_days: int | None = None,
        forward_days: int | None = None,
    ) -> SyncRecentMarketDataResultDTO:
        """Return an empty result without touching any provider."""
        return SyncRecentMarketDataResultDTO(
            requested_exchange_rates=0,
            requested_economic_indices=0,
            upserted_exchange_rates=0,
            upserted_economic_indices=0,
            upserted_brackets=0,
        )


def _stub_get_sync_use_case() -> _StubSyncUseCase:
    """FastAPI dependency override that returns the stub sync use case."""
    return _StubSyncUseCase()


def _wait_for_tcp(host: str, port: int, timeout: int = 30) -> None:
    """Poll host:port until the TCP handshake succeeds or timeout is reached.

    Required on Rancher Desktop where the host-side port-forward may lag
    a few seconds behind the container process being ready.
    """
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError(f"TCP {host}:{port} not ready after {timeout}s")


def _ensure_docker() -> None:
    """Ping Docker daemon; skip integration tests if unavailable."""
    try:
        import docker as _docker

        _docker.from_env().ping()
    except Exception:
        pytest.skip("Docker not available — skipping integration tests")


@pytest.fixture(scope="session")
def pg_url() -> str:
    """Start a PostgreSQL container, apply schema + seed, and return the async DSN."""
    _ensure_docker()

    with PostgresContainer("postgres:16-alpine") as pg:
        raw_url = pg.get_connection_url()
        # Normalise to asyncpg regardless of the driver returned by testcontainers.
        dsn = "postgresql+asyncpg://" + raw_url.split("://", 1)[1]
        _wait_for_tcp(pg.get_container_host_ip(), int(pg.get_exposed_port(5432)))

        async def _setup() -> None:
            # Use asyncpg directly for the multi-statement DDL/seed files;
            # asyncpg.connection.execute() handles multiple statements natively
            # whereas SQLAlchemy's prepared-statement layer does not.
            import asyncpg as _asyncpg

            pg_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
            conn = await _asyncpg.connect(dsn=pg_dsn, ssl=False)
            try:
                await conn.execute((_ROOT / "db" / "01_schema.sql").read_text())
                await conn.execute(
                    (_ROOT / "db" / "02_seed_currencies.sql").read_text()
                )
            finally:
                await conn.close()

        asyncio.run(_setup())
        yield dsn


@pytest.fixture
async def db_session(pg_url: str) -> AsyncSession:
    """Yield a live AsyncSession connected to the test database."""
    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
async def http_client(pg_url: str) -> AsyncClient:
    """Return an AsyncClient wired to a test DB session with no-op sync provider."""
    engine = create_async_engine(pg_url, **_TC_ENGINE_KWARGS)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session():  # type: ignore[return]
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_sync_use_case] = _stub_get_sync_use_case
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
