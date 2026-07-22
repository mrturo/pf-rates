# AGENTS.md — pf-rates

Dedicated microservice for Chilean financial reference data: exchange rates, economic indices, and income tax brackets.

## Architecture

Four layers; dependency flows inward only (interfaces → application → domain; infrastructure → application).

```
interfaces/      # FastAPI (adapter in)
application/     # Use cases, ports (Protocols), DTOs, services
domain/          # Pure quantization helpers — no I/O
infrastructure/  # SQLAlchemy, rate providers (adapters out)
shared/          # Cross-cutting constants
```

- `domain/` has zero external dependencies — pure Python only
- Ports (`application/ports/`) are `typing.Protocol` classes — never import concrete infrastructure types in the application layer
- Use cases are classes with `__init__` accepting port protocols; injected via `interfaces/api/dependencies.py`
- DTOs (`application/dto.py`) are the only data crossing layer boundaries

## Financial precision

- Always use `Decimal`, never `float` for monetary/rate values
- PostgreSQL columns use `NUMERIC`, never `FLOAT`
- Quantization helpers: `quantize_clp()` and `quantize_utm()` in `domain/quantizers.py`

## Language policy

- All code, identifiers, comments, docstrings, and files: English
- Exception: preserve official Chilean regulatory terms/source literals/seed values in original language only when translation alters meaning

## Code style

- ruff: `extend-select = ["D", "E", "W", "UP"]`, `pep257` convention
- Docstrings required for all modules, classes, and functions only
- PEPs: 484 (mypy), 544 (Protocols), 585 (`list[X]`), 604 (`X | None`), 498 (f-strings), 492 (async/await)
- Domain dataclasses: `@dataclass(slots=True)`; frozen value objects add `frozen=True`
- Async throughout; structlog only (`infrastructure/logging/logger.py`) — never `print` or stdlib `logging`

## Design principles

- Apply DRY, SOLID, Clean Code — avoid god objects; prefer small, focused classes
- Extract constants/mappings/literals to `shared/`; zero duplication in `src/` or `tests/`
- Orchestration logic belongs in use cases, not routes
- Never `assert` for production validation; raise from `application/errors.py`
- No silent fallbacks

## Development commands

```bash
# Database must be started from pf-db first (see Database section below)
make local-up              # check pf-db is running, write .env, install deps, run API
make env-write             # regenerate .env with default local DB values
make check                 # lint → dead-code → typecheck → dup-check → test → test-cov
# Individual: make lint | dead-code | typecheck | duplicate-code-src | duplicate-code-tests | test | test-cov
```

Run: `source .venv/bin/activate && make check` or `PATH=.venv/bin:$PATH make check`.

## Git hooks

Installed automatically by `make install` via `git config core.hooksPath .githooks`:

| Hook | Runs | Bypass |
|---|---|---|
| `pre-commit` | lint · dead-code · typecheck | `git commit --no-verify` |
| `pre-push` | duplicate-code-src · duplicate-code-tests | `git push --no-verify` |

## Testing conventions

- `tests/unit/` — no DB, no network; `tests/integration/` — live PostgreSQL via testcontainers
- No Mock library. Hand-rolled stubs per test file. See `tests/unit/application/test_refresh_rates.py`:

```python
class StubMarketDataRepository:
    def __init__(self) -> None:
        self.command: RefreshRatesCommandDTO | None = None
    async def refresh_rates(self, command: RefreshRatesCommandDTO) -> RefreshRatesResultDTO:
        self.command = command
        return RefreshRatesResultDTO(...)
```

- Shared fixtures in `tests/conftest.py`
- Integration tests bootstrap a throwaway postgres via testcontainers reading SQL fixtures
  directly from the pf-db repository (`db/01_schema.sql` and `db/02_seed_base.sql`).
  The path is resolved via the `PF_DB_PATH` env var (default: `../pf-db` — assumes sibling repos).
  In CI the `test` job checks out `mrturo/pf-db` into `_pf-db/` and sets `PF_DB_PATH=_pf-db`.
- Verify meaningful outputs (return values, state, errors) — not just that methods were called
- Mark async tests with `@pytest.mark.asyncio` (`asyncio_mode = "strict"` in `pyproject.toml`)
- 100% coverage required for `src/`

## Adding a new use case

1. Define/extend a port in `application/ports/` using `Protocol`
2. Create use case in `application/use_cases/` — constructor takes port interfaces only
3. Add DTOs to `application/dto.py`
4. Wire dependency in `interfaces/api/dependencies.py`
5. Add route in `interfaces/api/routes/`
6. Add stub-based unit test in `tests/unit/application/`
7. If the change requires a new column or table, add a migration in the pf-db repository
8. `make check` must pass clean

## CI/CD pipeline

`.github/workflows/deploy.yml` — six jobs:

| Job | Trigger | Action |
|---|---|---|
| `test` | PR + push `main` | lint, vulture, mypy, jscpd, pytest+coverage |
| `build` | PR + push `main` | Docker build, Trivy scan (SARIF + blocking gate on CRITICAL/HIGH) |
| `gate` | push `main` | manual approval via `production` environment |
| `deploy` | push `main` | push image to AR, deploy Cloud Run |
| `notify-failure` | any job failure on `main` | SMTP failure email |
| `notify-success` | successful deploy | SMTP success email |

Pipeline invariants (never violate):

1. Migrations before traffic — the `pf-db` Cloud Run Job must apply all pending migrations before either service receives traffic. pf-rates ships no migration tooling.
2. DB URL via `--set-secrets` only — never `--set-env-vars`
3. AR scanning stays disabled — pipeline uses Trivy (~$5/month if enabled)
4. `--min-instances=0` — intentional scale-to-zero; do not change without approval
5. Image tagged with both `github.sha` and `latest` — deploy references SHA, not `latest`
6. Non-root container — Dockerfile switches to `appuser` in final stage
7. Multi-stage build — final stage copies only the venv; do not add `COPY src ./src`

GitHub Secrets:

| Secret | Purpose |
|---|---|
| `GCP_SA_KEY` | GCP auth (deploy job) |
| `GCP_PROJECT_ID` | image tags, IAM |
| `PF_DATABASE_URL` | Cloud Run `--set-secrets` (points to shared pf-db instance) |
| `PF_RATES_API_KEY` | Cloud Run `--set-secrets` |
| `GCP_CLOUD_SQL_INSTANCE` | optional Cloud SQL proxy sidecar |
| `MAIL_SERVER/PORT/USERNAME/PASSWORD/FROM/TO` | SMTP notifications |

> `FINANCIAL_DATA_BCCH_API_USER` / `BCCH_API_PASSWORD` referenced in workflow header but not injected — add `--set-secrets` if needed at runtime.

DB options: A) External — set `PF_DATABASE_URL` → shared Neon/Supabase pf-db instance, leave `GCP_CLOUD_SQL_INSTANCE` empty. B) Cloud SQL — set `GCP_CLOUD_SQL_INSTANCE=PROJECT:us-central1:pf-db`, pipeline adds proxy sidecar.

Cloud Run: region `us-central1`, min 0/max 2 instances, 512 MiB/1 CPU, port 8080, SA `pf-rates@<PROJECT>.iam.gserviceaccount.com` needs `roles/secretmanager.secretAccessor`.

## Versioning and operations

- SemVer; Conventional Commits (English)
- Never autonomously commit, push branches, create issues, or open PRs — requires explicit user command

## Database

Schema and migrations are owned by **pf-db** — a separate repository.
pf-rates only holds SQLAlchemy ORM models and repositories.

- **Connection**: `PF_DATABASE_URL` env var (default local: `postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db`)
- **Sessions**: `infrastructure/db/session.py` — always use `async with SessionLocal() as session`
- **Repositories**: implement port `Protocol`s; live in `infrastructure/db/repositories/`
- **ORM models**: `infrastructure/db/models/financial_data.py`
- **Schema changes**: add a migration in the pf-db repository — never edit models without a corresponding pf-db migration

### Local database setup

pf-rates no longer manages its own postgres container. Start the shared database from pf-db:

```bash
cd ../pf-db
make local-up        # start postgres + apply schema + load base seed
```

Then start pf-rates:

```bash
cd ../pf-rates
make local-up        # verifies pf-db is running, writes .env, runs API
```

### Tables owned by pf-rates

`currencies` · `exchange_rates` · `economic_indices` · `income_tax_brackets`

These tables are written exclusively by pf-rates. `pf-payroll` reads them via the pf-rates HTTP API — never via direct SQL.

### SQL test fixtures

Integration tests read SQL fixtures directly from the pf-db repository — no local copies.
Set `PF_DB_PATH` in `.env` (default: `../pf-db`) to point to the pf-db checkout.
