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
make db-up              # start PostgreSQL, apply schema + seed
make run                # start FastAPI with auto-reload
```

Once running, the interactive docs are available at:

- **Swagger UI** → `http://localhost:8001/docs`
- **ReDoc** → `http://localhost:8001/redoc`

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Service liveness check. |
| `GET` | `/currencies` | List all supported currencies. |
| `GET` | `/exchange-rates` | List exchange rates. Filter: `?currency_code=USD` |
| `GET` | `/exchange-rates/value` | CLP value for a currency on a date. Params: `currency_code`, `rate_date` |
| `POST` | `/exchange-rates/refresh` | Upsert exchange rates from manual entries or provider fetches. |
| `GET` | `/economic-indices` | List economic indices. Filter: `?code=UF` |
| `GET` | `/economic-indices/value` | Index value for a code and period. Params: `code`, `year`, `month` |
| `POST` | `/economic-indices/refresh` | Upsert economic indices from manual entries or provider fetches. |
| `GET` | `/income-tax-brackets` | Matching bracket for a payment date and taxable base. Params: `payment_date`, `taxable_base_utm` |
| `GET` | `/income-tax-brackets/list` | List all brackets for a year. Param: `year` |
| `POST` | `/income-tax-brackets/refresh` | Fetch and persist official brackets for a year. |
| `POST` | `/sync` | Rolling sync of all missing market data. Optional body: `{"lookback_days": 365, "forward_days": 35}`. UF includes pre-published future values. |

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
