# AGENTS.md — pf-rates

Dedicated microservice for Chilean financial reference data: exchange rates, economic indices, and income tax brackets.

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
- Ports (`application/ports/`) are `typing.Protocol` classes — never import concrete infrastructure types in the application layer
- Use cases are `@dataclass(slots=True)` classes whose `__init__` accepts port protocols; injected at the interface layer via `interfaces/api/dependencies.py`
- DTOs (`application/dto.py`) are the only data crossing layer boundaries

## Financial precision

- **Always use `Decimal`, never `float`** for any monetary or rate value
- PostgreSQL columns for money/rates use `NUMERIC`, never `FLOAT`
- Quantization helpers: `quantize_clp()` and `quantize_utm()` in `domain/quantizers.py`

## Language policy

- All code, identifiers, comments, docstrings, and files must be in **English**
- Exception: preserve official domain/regulatory terms (e.g., Chilean law names), source literals, and seed values in their original language only when translation would alter meaning — surrounding code and docs stay English

## Code style

- PEP 8 + PEP 257 enforced via ruff (`extend-select = ["D", "E", "W", "UP"]`, `convention = "pep257"`)
- Docstrings are required for **public** modules, classes, and functions only; internal helpers use minimal inline comments
- PEPs in force: 484 (types/mypy), 544 (Protocols for ports), 585 (built-in generics `list[X]`), 604 (`X | None` unions), 498 (f-strings), 492 (async/await), 621 (pyproject.toml)
- Domain dataclasses use `@dataclass(slots=True)`; frozen value objects add `frozen=True`
- Async throughout: all repository and use-case methods are `async def`
- structlog for all logging (`infrastructure/logging/logger.py`) — never use `print` or stdlib `logging` directly

## Design principles

- Apply DRY, SOLID, Clean Code — avoid god objects; prefer small, focused classes
- Extract repeated constants, mappings, and literals to `shared/`; zero tolerance for duplication in `src/` or `tests/`
- Thin interface layers (HTTP): orchestration logic belongs in use cases, not routes
- Validations must be explicit and placed close to layer boundaries or domain rules
- Never use `assert` for production validation; raise explicit errors from `application/errors.py`
- No silent fallbacks

## Development commands

```bash
# Local stack
make local-up              # start DB, write .env, start Adminer, install deps, run API
make db-up                 # start/reuse PostgreSQL (Rancher Desktop)
make env-write             # regenerate .env with default local DB values

# Validation (run before every commit)
make check                 # lint → dead-code → typecheck → dup-check → test → test-cov

# Individual steps
make lint                  # ruff auto-fix + validate
make dead-code             # vulture (unused production code in src/)
make typecheck             # mypy
make duplicate-code-src    # jscpd (1% threshold)
make duplicate-code-tests  # jscpd (10% threshold)
make test                  # pytest
make test-cov              # pytest with 100% coverage enforcement
```

Run with virtualenv active (`source .venv/bin/activate && make check`) or inline (`PATH=.venv/bin:$PATH make check`).

## Testing conventions

**Test location:**
- `tests/unit/` — pure unit tests; no database, no network
- `tests/integration/` — live PostgreSQL via testcontainers; uses `AsyncClient`

**Stub pattern (no Mock library):**
Write hand-rolled stub classes per test file. Do not use `unittest.mock.Mock` or `MagicMock`. See `tests/unit/application/test_refresh_rates.py` for the canonical pattern:

```python
class StubMarketDataRepository:
    def __init__(self) -> None:
        self.saved: list[object] = []

    async def save(self, items):
        self.saved = items
        return RefreshRatesResultDTO(...)
```

**Shared fixtures** go in `tests/conftest.py`.

**Assertion quality:** tests must verify meaningful outputs (return values, state, error messages). Avoid assertions that only confirm a method was called.

**Async tests:** `asyncio_mode = "auto"` is set in `pyproject.toml` — do **not** add `@pytest.mark.asyncio`.

**Coverage:** `src/` requires 100% coverage — every new code path needs a test.

## Adding a new use case

1. Define or extend a port in `application/ports/` using `Protocol`
2. Create the use case class in `application/use_cases/` — constructor takes port interfaces only
3. Add DTOs to `application/dto.py`
4. Wire the dependency in `interfaces/api/dependencies.py`
5. Add a route in `interfaces/api/routes/`
6. Add a stub-based unit test in `tests/unit/application/`
7. Run `make check` — it must pass clean

## CI/CD pipeline

The pipeline lives in `.github/workflows/deploy.yml`. It has three jobs:

- **`test`** — triggered on every PR and push to `main`. Runs lint, static analysis (vulture, mypy, jscpd), and pytest with coverage. No Docker.
- **`build`** — triggered on every PR and push to `main` (needs: `test`). Builds the Docker image locally, exports it to a tar file, and runs **Trivy** in two passes: SARIF upload to GitHub Security (exit 0) and a blocking gate on unfixed CRITICAL/HIGH CVEs (exit 1). On push to `main` only: tags the image for Artifact Registry and uploads it as a GitHub Actions artifact (expires after 1 day).
- **`deploy`** — triggered only on push to `main` via the `GCP` GitHub environment (needs: `build`). Authenticates to GCP, asserts AR scanning is disabled, loads the image artifact and pushes it to Artifact Registry, runs Alembic migrations as a Cloud Run Job with `--wait`, then deploys the Cloud Run Service.

**Non-negotiable invariants when editing the pipeline:**

1. **Migrations run before traffic.** The `pf-rates-migrate` Cloud Run Job executes `alembic upgrade head` with `--wait` and `--max-retries=0`. Do not route traffic to a new revision until this job completes successfully.
2. **DB URL only from Secret Manager.** `FINANCIAL_DATA_DATABASE_URL` is injected via `--set-secrets`, never `--set-env-vars`. Do not add it to environment variables.
3. **AR vulnerability scanning must stay disabled.** The deploy step checks `vulnerabilityScanningConfig.enablementConfig` and blocks if `ENABLED`. Enabling it incurs ~$5/month per image. The pipeline uses Trivy instead.
4. **Scale-to-zero is intentional.** `--min-instances=0` keeps compute cost at zero at rest. Do not change this without explicit approval.
5. **Image tagged with `github.sha` and `latest`.** Both tags are pushed. The migration job and service deploy reference the SHA tag — do not replace it with `latest` alone (immutability).
6. **Non-root container.** The Dockerfile creates and switches to `appuser` in the final stage. Do not run as root.
7. **Multi-stage Docker build.** The builder stage installs deps; the final stage copies only the venv and `alembic/`. Do not add `COPY src ./src` to the final stage — the package is already installed in the venv.

**GitHub Secrets used by the pipeline:**

| Secret | Where used |
| --- | --- |
| `GCP_SA_KEY` | `google-github-actions/auth` (deploy job) |
| `GCP_PROJECT_ID` | `setup-gcloud`, image tags, IAM references |
| `FINANCIAL_DATA_DATABASE_URL` | Injected into Cloud Run migration job and service via `--set-secrets` at runtime |
| `FINANCIAL_DATA_API_KEY` | Injected into Cloud Run migration job and service via `--set-secrets` at runtime |
| `GCP_CLOUD_SQL_INSTANCE` | Optional — adds `--set-cloudsql-instances` / `--add-cloudsql-instances` flags when non-empty |

> `FINANCIAL_DATA_BCCH_API_USER` and `FINANCIAL_DATA_BCCH_API_PASSWORD` are listed in the workflow header as references but are **not currently injected** into Cloud Run steps. Add explicit `--set-secrets` entries if they are needed at runtime.

**Database options (A vs B):**

- **Option A (external DB):** set `FINANCIAL_DATA_DATABASE_URL` in Secret Manager pointing to an external host (e.g. Neon, Supabase). Leave `GCP_CLOUD_SQL_INSTANCE` empty — no Cloud SQL flags are added.
- **Option B (Cloud SQL):** set `GCP_CLOUD_SQL_INSTANCE=PROJECT:us-central1:pf-rates-db`. The pipeline adds the Cloud SQL proxy sidecar to both the migration job and the service.

**Cloud Run configuration (as deployed):**

- Region: `us-central1`
- Instances: min 0, max 2
- Memory: 512 MiB; CPU: 1
- Port: 8080 (`PORT` injected by Cloud Run at runtime; Dockerfile defaults to 8080)
- Runtime SA: `pf-rates@<PROJECT>.iam.gserviceaccount.com` — must hold `roles/secretmanager.secretAccessor` on the DB secret

## Versioning and operations

- **SemVer** for version numbers
- **Conventional Commits** (English) for all git messages
- Follow 12-Factor: configuration via env vars, explicit dependencies, stateless/disposable processes, logs to stdout/stderr
- Never autonomously execute git commits, push branches, create issues, or open PRs — each requires an explicit user command

## Database

- Schema: `db/01_schema.sql` (idempotent DDL — `CREATE TABLE IF NOT EXISTS`)
- Seed: `db/02_seed_currencies.sql`
- Migrations: Alembic (`alembic/`)
- Connection string uses `FINANCIAL_DATA_DATABASE_URL` env var (prefix `FINANCIAL_DATA_`)
