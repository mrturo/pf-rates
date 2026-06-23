# pf-rates

Microservice for Chilean financial reference data: exchange rates, economic indices, and income tax brackets.

## Overview

This repository implements a dedicated microservice for Chilean financial reference data with:

- exchange rates (USD, EUR) sourced from Mindicador and Banco Central de Chile (BCCH)
- economic indices (UF, UTM, IPC) from official Chilean sources
- income tax brackets for payroll tax calculation
- FastAPI API
- PostgreSQL persistence with Alembic migrations and local Rancher Desktop workflows

## Quick start

```bash
make install            # create virtualenv + install deps
make env-write          # generate .env with default local values
                        # then edit .env and set FINANCIAL_DATA_API_KEY to a secure value
make db-up              # start PostgreSQL, apply schema + seed
make run                # start FastAPI with auto-reload
```

Once running, the interactive docs are available at:

- **Swagger UI** → `http://localhost:8001/docs` (use the "Authorize" button to set `X-API-Key`)
- **ReDoc** → `http://localhost:8001/redoc`

## Deployment (GCP Cloud Run)

The service is deployed to **Google Cloud Run** via **GitHub Actions** (`.github/workflows/deploy.yml`).

### Pipeline overview

| Event | Jobs |
| --- | --- |
| Pull request → `main` | `test` → `build` (lint, pytest, Docker build, Trivy scan) |
| Push → `main` | `test` → `build` → `deploy` (push image to AR, migrate, deploy) |

**`test` job** — runs on every PR and push:
1. Lint with ruff, run static analysis (vulture, mypy, jscpd), and run pytest with coverage. No Docker.

**`build` job** — runs on every PR and push (needs: `test`):
1. Build the Docker image locally (not pushed) for scanning.
2. Scan the image with **Trivy**: uploads a SARIF report to the GitHub Security tab and blocks the pipeline on unfixed CRITICAL/HIGH CVEs.
3. On push to `main` only: tag the image for Artifact Registry and upload it as a GitHub Actions artifact (expires after 1 day).

**`deploy` job** — runs only on push to `main`, requires the `GCP` GitHub environment (needs: `build`):
1. Authenticate to GCP using a service-account key.
2. Assert that Artifact Registry vulnerability scanning is disabled (cost control — ~$5/month per image if enabled).
3. Load the image artifact and push it to Artifact Registry (`us-central1`, repository `pf-rates`) tagged with the commit SHA and `latest`.
4. Deploy a Cloud Run **Job** (`pf-rates-migrate`) that runs `alembic upgrade head` and waits for it to succeed before any traffic is shifted.
5. Deploy the Cloud Run **Service** (`pf-rates`) with the new image.

### Database options

The pipeline supports two database configurations, controlled by the optional `GCP_CLOUD_SQL_INSTANCE` secret:

| Option | Setup | `GCP_CLOUD_SQL_INSTANCE` |
| --- | --- | --- |
| **A — external DB** (e.g. Neon, Supabase) | Set `FINANCIAL_DATA_DATABASE_URL` in Secret Manager pointing to the external host | leave the secret **empty** |
| **B — Cloud SQL** | Create a `db-f1-micro` Cloud SQL instance (`pf-rates-db`, `us-central1`) | set to `PROJECT:us-central1:pf-rates-db` |

### GitHub Secrets

Configure the following secrets in the repository (Settings → Secrets and variables → Actions):

| Secret | Required | Description |
| --- | --- | --- |
| `GCP_SA_KEY` | ✅ | Service-account JSON key with the roles listed in the deploy workflow header. |
| `GCP_PROJECT_ID` | ✅ | GCP project ID. |
| `FINANCIAL_DATA_DATABASE_URL` | ✅ | Connection string stored in Secret Manager (injected into Cloud Run at runtime). |
| `FINANCIAL_DATA_API_KEY` | ✅ | API key for client authentication; stored in Secret Manager and injected into both the migration job and the service at runtime. |
| `GCP_CLOUD_SQL_INSTANCE` | optional | Cloud SQL instance in `PROJECT:REGION:INSTANCE` format (leave empty for Option A). |

> **BCCH credentials** (`FINANCIAL_DATA_BCCH_API_USER` / `FINANCIAL_DATA_BCCH_API_PASSWORD`) are listed in the workflow header for reference. They are not currently injected into Cloud Run automatically — add `--set-secrets` entries in the deploy step if your environment requires them.

### Cloud Run configuration

- **Region:** `us-central1`
- **Scale:** min 0 → max 2 instances (scales to zero when idle — zero compute cost at rest)
- **Resources:** 512 MiB RAM, 1 vCPU
- **Port:** 8080 (Cloud Run injects `PORT` at runtime)
- **Secrets at runtime:** `FINANCIAL_DATA_DATABASE_URL` is read from Secret Manager; it is never stored in environment variables.

### One-time GCP setup

The full bootstrap sequence (enable APIs, create Artifact Registry repository, Cloud SQL instance, Secret Manager secret, service account, IAM bindings) is documented in the comment block at the top of `.github/workflows/deploy.yml`.

## API

All endpoints except `GET /health` require the `X-API-Key` header. Set it via the **Authorize** button in Swagger UI or pass it explicitly in every request:
```
X-API-Key: <your-key>
```

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/health` | — | Service liveness check. |
| `GET` | `/currencies` | 🔑 | List all supported currencies. |
| `GET` | `/exchange-rates` | 🔑 | List exchange rates. Filter: `?currency_code=USD` |
| `GET` | `/exchange-rates/value` | 🔑 | CLP value for a currency on a date. Params: `currency_code`, `rate_date` |
| `POST` | `/exchange-rates/refresh` | 🔑 | Upsert exchange rates from manual entries or provider fetches. |
| `GET` | `/economic-indices` | 🔑 | List economic indices. Filter: `?code=UF` |
| `GET` | `/economic-indices/value` | 🔑 | Index value for a code and period. Params: `code`, `year`, `month` |
| `POST` | `/economic-indices/refresh` | 🔑 | Upsert economic indices from manual entries or provider fetches. |
| `GET` | `/income-tax-brackets` | 🔑 | Matching bracket for a reference date and taxable base. Params: `reference_date`, `taxable_base_utm` |
| `GET` | `/income-tax-brackets/list` | 🔑 | List all brackets for a year. Param: `year` |
| `POST` | `/income-tax-brackets/refresh` | 🔑 | Fetch and persist official brackets for a year. |
| `POST` | `/sync` | 🔑 | Rolling sync of all missing market data. Optional body: `{"lookback_days": 365, "forward_days": 35}`. UF includes pre-published future values. |

## Engineering policy

This repository adopts the following engineering standards and conventions:

- **PEP 8** for Python style and formatting.
- **PEP 257** for module, package, class, function, method, and script docstrings.
- **PEP 484** for type hints across public contracts and application flows.
- **PEP 544** for structural contracts via `Protocol` in application ports.
- **PEP 585** for built-in generic types such as `list[str]`.
- **PEP 604** for union syntax such as `X | None`.
- **PEP 498** for preferred string interpolation via f-strings.
- **PEP 492** for explicit asynchronous I/O with `async` / `await`.
- **PEP 621** for project metadata in `pyproject.toml`.
- **SemVer** for project versioning.
- **Twelve-Factor** principles for configuration, dependency declaration, disposability, stateless execution, and logging.

## Repository structure

- `src/financial_data/domain`: quantization helpers
- `src/financial_data/application`: use cases and ports
- `src/financial_data/infrastructure`: database, rate providers, logging
- `src/financial_data/interfaces`: FastAPI entrypoint
- `tests`: unit and integration coverage
- `db`: SQL schema and seed data
- `alembic`: database migrations
