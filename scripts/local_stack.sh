#!/usr/bin/env bash
set -euo pipefail

NERDCTL_BIN="${NERDCTL_BIN:-nerdctl}"
DB_CONTAINER="${DB_CONTAINER:-pf-rates-postgres}"
DB_VOLUME="${DB_VOLUME:-pf-rates-postgres-data}"
DB_NAME="${DB_NAME:-rates}"
DB_USER="${DB_USER:-rates}"
DB_PASSWORD="${DB_PASSWORD:-rates}"
DB_PORT="${DB_PORT:-5433}"
ADMINER_CONTAINER="${ADMINER_CONTAINER:-pf-rates-adminer}"
ADMINER_PORT="${ADMINER_PORT:-8090}"
APP_PORT="${APP_PORT:-8001}"
VENV="${VENV:-.venv}"
ENV_FILE="${ENV_FILE:-.env}"
CORPORATIVE_PIP_INDEX="${CORPORATIVE_PIP_INDEX:-}"
CORPORATIVE_NPM_REGISTRY="${CORPORATIVE_NPM_REGISTRY:-}"

log() {
  printf '[local-up] %s\n' "$1"
}

venv_ready() {
  [[ -x "$VENV/bin/python" ]] && [[ -x "$VENV/bin/uvicorn" ]] && \
    "$VENV/bin/python" -c "import financial_data, fastapi, asyncpg, pydantic_settings, sqlalchemy, uvicorn" >/dev/null 2>&1
}

log "Starting or reusing PostgreSQL"
NERDCTL_BIN="$NERDCTL_BIN" \
DB_CONTAINER="$DB_CONTAINER" \
DB_VOLUME="$DB_VOLUME" \
DB_NAME="$DB_NAME" \
DB_USER="$DB_USER" \
DB_PASSWORD="$DB_PASSWORD" \
DB_PORT="$DB_PORT" \
./scripts/db.sh up

log "Starting or reusing Adminer"
adminer_output="$(
  NERDCTL_BIN="$NERDCTL_BIN" \
  ADMINER_CONTAINER="$ADMINER_CONTAINER" \
  ADMINER_PORT="$ADMINER_PORT" \
  ./scripts/adminer.sh up
)"
printf '%s\n' "$adminer_output"
adminer_url="$(printf '%s\n' "$adminer_output" | tail -n 1)"

log "Writing environment file to $ENV_FILE"
{
  printf 'FINANCIAL_DATA_DATABASE_URL=postgresql+asyncpg://%s:%s@localhost:%s/%s\n' \
    "$DB_USER" "$DB_PASSWORD" "$DB_PORT" "$DB_NAME"
  printf '\n# Tooling — corporate pip/npm registries (used by make install/check on VPN)\n'
  printf 'CORPORATIVE_PIP_INDEX=%s\n' "$CORPORATIVE_PIP_INDEX"
  printf 'CORPORATIVE_NPM_REGISTRY=%s\n' "$CORPORATIVE_NPM_REGISTRY"
} > "$ENV_FILE"

if venv_ready; then
  log "Reusing existing virtual environment in $VENV"
else
  log "Installing project dependencies"
  if [[ ! -x "$VENV/bin/python" ]]; then
    python3 -m venv "$VENV"
  fi
  "$VENV/bin/python" -m ensurepip --upgrade
  "$VENV/bin/python" -m pip install -e ".[dev]"
fi

printf '\n'
printf 'Adminer : %s\n' "$adminer_url"
printf 'API     : http://127.0.0.1:%s\n' "$APP_PORT"
printf 'Docs    : http://127.0.0.1:%s/docs\n' "$APP_PORT"
printf 'Env     : %s\n' "$ENV_FILE"
printf '\n'

exec "$VENV/bin/uvicorn" financial_data.interfaces.api.app:app --reload --host 127.0.0.1 --port "$APP_PORT"
