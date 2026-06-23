"""Tests for the FastAPI app lifespan and startup sync."""

import asyncio
import os

import pytest

import financial_data.interfaces.api.app as app_module
from financial_data.application.dto import SyncRecentMarketDataResultDTO
from financial_data.application.use_cases.refresh_income_tax_brackets import (
    RefreshIncomeTaxBrackets,
)
from financial_data.infrastructure.db.repositories.reference_data_repository import (
    SqlAlchemyReferenceDataRepository,
)
from financial_data.interfaces.api.dependencies import (
    get_refresh_income_tax_brackets_use_case,
)


# ---------------------------------------------------------------------------
# _run_startup_sync branches
# ---------------------------------------------------------------------------


async def test_startup_sync_returns_early_during_pytest() -> None:
    """_run_startup_sync exits immediately when PYTEST_CURRENT_TEST is set."""
    assert "PYTEST_CURRENT_TEST" in os.environ
    # Should complete without any I/O or exception
    await app_module._run_startup_sync()


async def test_startup_sync_handles_exception_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_startup_sync catches exceptions and returns without raising."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    class _FailingContext:
        async def __aenter__(self) -> None:
            raise RuntimeError("DB unavailable")

        async def __aexit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(app_module, "SessionLocal", lambda: _FailingContext())

    await app_module._run_startup_sync()  # must not raise


async def test_startup_sync_propagates_cancelled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_startup_sync re-raises asyncio.CancelledError."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    class _CancelledContext:
        async def __aenter__(self) -> None:
            raise asyncio.CancelledError()

        async def __aexit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(app_module, "SessionLocal", lambda: _CancelledContext())

    with pytest.raises(asyncio.CancelledError):
        await app_module._run_startup_sync()


async def test_startup_sync_logs_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_startup_sync completes and logs when the use case succeeds."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    _RESULT = SyncRecentMarketDataResultDTO(
        requested_exchange_rates=2,
        requested_economic_indices=1,
        upserted_exchange_rates=2,
        upserted_economic_indices=1,
    )

    class _StubUseCase:
        async def execute(self) -> SyncRecentMarketDataResultDTO:
            return _RESULT

    class _StubSession:
        async def __aenter__(self) -> "_StubSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(app_module, "SessionLocal", lambda: _StubSession())
    monkeypatch.setattr(
        app_module, "build_sync_use_case", lambda session: _StubUseCase()
    )

    await app_module._run_startup_sync()


# ---------------------------------------------------------------------------
# lifespan
# ---------------------------------------------------------------------------


async def test_lifespan_cancels_running_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan cancels the startup-sync task if it's still running on exit."""
    cancelled = asyncio.Event()

    async def _slow_sync() -> None:
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(app_module, "_run_startup_sync", _slow_sync)

    async with app_module.lifespan(app_module.app):
        task = app_module.app.state.market_data_sync_task
        await asyncio.sleep(0)  # Let the task start before we exit the context
        assert isinstance(task, asyncio.Task)
        assert not task.done()

    # Give the event loop a tick to process the cancellation
    await asyncio.sleep(0)
    assert cancelled.is_set()
    assert task.cancelled()


async def test_lifespan_skips_cancel_when_task_already_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan does not cancel a task that already completed."""

    async def _quick_sync() -> None:
        return

    monkeypatch.setattr(app_module, "_run_startup_sync", _quick_sync)

    async with app_module.lifespan(app_module.app):
        task = app_module.app.state.market_data_sync_task
        await task  # wait for immediate completion

    assert task.done()
    assert not task.cancelled()


# ---------------------------------------------------------------------------
# Dependencies smoke tests
# ---------------------------------------------------------------------------


def test_get_fx_rate_provider_returns_chained_provider() -> None:
    """get_fx_rate_provider builds a ChainedFxProvider without error."""
    from financial_data.infrastructure.rate_providers.chained_provider import (
        ChainedFxProvider,
    )
    from financial_data.interfaces.api.dependencies import get_fx_rate_provider

    provider = get_fx_rate_provider()
    assert isinstance(provider, ChainedFxProvider)


def test_get_economic_index_provider_returns_chained_provider() -> None:
    """get_economic_index_provider builds a ChainedEconomicIndexProvider."""
    from financial_data.infrastructure.rate_providers.chained_provider import (
        ChainedEconomicIndexProvider,
    )
    from financial_data.interfaces.api.dependencies import get_economic_index_provider

    provider = get_economic_index_provider()
    assert isinstance(provider, ChainedEconomicIndexProvider)


def test_get_income_tax_bracket_provider_returns_sii_provider() -> None:
    """get_income_tax_bracket_provider builds a SiiIncomeTaxBracketProvider."""
    from financial_data.infrastructure.rate_providers.official_providers import (
        SiiIncomeTaxBracketProvider,
    )
    from financial_data.interfaces.api.dependencies import (
        get_income_tax_bracket_provider,
    )

    provider = get_income_tax_bracket_provider()
    assert isinstance(provider, SiiIncomeTaxBracketProvider)


def test_build_sync_use_case_returns_use_case() -> None:
    """build_sync_use_case constructs a SyncRecentMarketData from any session."""
    from financial_data.application.use_cases.sync_recent_market_data import (
        SyncRecentMarketData,
    )
    from financial_data.interfaces.api.dependencies import build_sync_use_case

    class _FakeSession:
        pass

    use_case = build_sync_use_case(_FakeSession())  # type: ignore[arg-type]
    assert isinstance(use_case, SyncRecentMarketData)


def test_get_refresh_rates_use_case_builds_correctly() -> None:
    """get_refresh_rates_use_case assembles a RefreshRates with providers."""
    from financial_data.application.use_cases.refresh_rates import RefreshRates
    from financial_data.infrastructure.db.repositories.market_data_repository import (
        SqlAlchemyMarketDataRepository,
    )
    from financial_data.interfaces.api.dependencies import get_refresh_rates_use_case

    class _FakeSession:
        pass

    repository = SqlAlchemyMarketDataRepository(_FakeSession())  # type: ignore[arg-type]
    use_case = get_refresh_rates_use_case(repository)
    assert isinstance(use_case, RefreshRates)
    assert use_case.fx_provider is not None
    assert use_case.economic_index_provider is not None


def test_get_refresh_income_tax_brackets_use_case_builds_correctly() -> None:
    """get_refresh_income_tax_brackets_use_case assembles the use case."""

    class _FakeSession:
        pass

    repository = SqlAlchemyReferenceDataRepository(_FakeSession())  # type: ignore[arg-type]
    use_case = get_refresh_income_tax_brackets_use_case(repository)
    assert isinstance(use_case, RefreshIncomeTaxBrackets)


def test_get_sync_use_case_builds_use_case() -> None:
    """get_sync_use_case constructs a SyncRecentMarketData."""
    from financial_data.application.use_cases.sync_recent_market_data import (
        SyncRecentMarketData,
    )
    from financial_data.interfaces.api.dependencies import get_sync_use_case

    class _FakeSession:
        pass

    use_case = get_sync_use_case(_FakeSession())  # type: ignore[arg-type]
    assert isinstance(use_case, SyncRecentMarketData)


def test_get_market_data_repository_returns_sqla_repository() -> None:
    """get_market_data_repository wraps the session in the SQLAlchemy implementation."""
    from financial_data.infrastructure.db.repositories.market_data_repository import (
        SqlAlchemyMarketDataRepository,
    )
    from financial_data.interfaces.api.dependencies import get_market_data_repository

    class _FakeSession:
        pass

    repo = get_market_data_repository(_FakeSession())  # type: ignore[arg-type]
    assert isinstance(repo, SqlAlchemyMarketDataRepository)


def test_get_reference_data_repository_returns_sqla_repository() -> None:
    """get_reference_data_repository returns the SQLAlchemy implementation."""
    from financial_data.infrastructure.db.repositories.reference_data_repository import (  # noqa: E501
        SqlAlchemyReferenceDataRepository,
    )
    from financial_data.interfaces.api.dependencies import get_reference_data_repository

    class _FakeSession:
        pass

    repo = get_reference_data_repository(_FakeSession())  # type: ignore[arg-type]
    assert isinstance(repo, SqlAlchemyReferenceDataRepository)


async def test_get_session_yields_session_from_session_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_session yields the session produced by SessionLocal."""
    import financial_data.interfaces.api.dependencies as deps_module

    class _StubSession:
        async def __aenter__(self) -> "_StubSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(deps_module, "SessionLocal", lambda: _StubSession())

    yielded: list[object] = []
    async for session in deps_module.get_session():
        yielded.append(session)

    assert len(yielded) == 1
    assert isinstance(yielded[0], _StubSession)
