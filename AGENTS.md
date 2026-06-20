# AGENTS.md — pf-rates

Dedicated microservice for Chilean financial reference data: exchange rates, economic indices, and income tax brackets. Extracted from pf-payroll. Applies identical hexagonal conventions.

---

## Architecture

Four layers; dependency flows inward only (interfaces → application → domain; infrastructure → application).

```
interfaces/      # FastAPI (adapter in)
application/     # Use cases, ports (Protocols), DTOs, services
domain/          # Pure quantization helpers — no I/O
infrastructure/  # SQLAlchemy, rate providers (adapters out)
shared/          # Cross-cutting constants
```

**Key rules:**
- `domain/` has zero external dependencies — pure Python only
- Ports (`application/ports/`) are `typing.Protocol` classes
- Use cases are `@dataclass(slots=True)` classes whose `__init__` accepts port protocols
- DTOs (`application/dto.py`) are the only data crossing layer boundaries
- Dependency injection wired at `interfaces/api/dependencies.py`

## Financial precision

- **Always use `Decimal`, never `float`** for any monetary or rate value
- PostgreSQL columns for money/rates use `NUMERIC`, never `FLOAT`
- Quantization helpers: `quantize_clp()` and `quantize_utm()` in `domain/quantizers.py`

## Language policy

All code, identifiers, comments, docstrings, and files must be in **English**. Official domain terms (e.g., Chilean law names, source literals, seed values) may stay in their original language.

## Code style

- PEP 8 + PEP 257 enforced via ruff (`extend-select = ["D", "E", "W", "UP"]`, `convention = "pep257"`)
- Domain dataclasses use `@dataclass(slots=True)`; frozen value objects add `frozen=True`
- Async throughout: all repository and use-case methods are `async def`
- structlog for all logging (`infrastructure/logging/logger.py`) — never `print` or stdlib `logging`

## Design principles

- Apply DRY, SOLID, Clean Code — avoid god objects
- Never use `assert` for production validation; raise explicit errors from `application/errors.py`
- No silent fallbacks

## Development commands

```bash
make install            # create virtualenv + install deps
make env-write          # regenerate .env with default local values
make db-up              # start PostgreSQL, apply schema + seed
make run                # start FastAPI with auto-reload
make check              # lint → dead-code → typecheck → dup-check → test → test-cov
```

## Testing conventions

- `tests/unit/` — pure unit tests; no database, no network
- `tests/integration/` — live PostgreSQL via testcontainers; uses AsyncClient
- Stubs: hand-rolled stub classes only — no `unittest.mock.Mock` or `MagicMock`
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` required
- Coverage: `src/` requires 100%

## Database

- Schema: `db/01_schema.sql` (idempotent DDL — `CREATE TABLE IF NOT EXISTS`)
- Seed: `db/02_seed_currencies.sql`
- Connection string uses `FINANCIAL_DATA_DATABASE_URL` env var (prefix `FINANCIAL_DATA_`)
