#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-up}"
NERDCTL_BIN="${NERDCTL_BIN:-nerdctl}"
CLI=()  # populated by select_runtime as an array to support multi-word commands
DB_CONTAINER="${DB_CONTAINER:-pf-rates-postgres}"
DB_VOLUME="${DB_VOLUME:-pf-rates-postgres-data}"
DB_NAME="${DB_NAME:-rates}"
DB_USER="${DB_USER:-rates}"
DB_PASSWORD="${DB_PASSWORD:-rates}"
DB_PORT="${DB_PORT:-5433}"
SCHEMA_FILE="${SCHEMA_FILE:-db/01_schema.sql}"
BASE_SEED_FILE="${BASE_SEED_FILE:-db/02_seed_currencies.sql}"
TEST_SEED_FILE="${TEST_SEED_FILE:-db/03_seed_test.sql}"
REAL_SEED_FILE="${REAL_SEED_FILE:-db/03_seed_real.sql}"
APPLY_TEST_SEED="${APPLY_TEST_SEED:-0}"
APPLY_REAL_SEED="${APPLY_REAL_SEED:-0}"

log() {
  printf '[db] %s\n' "$1"
}

# shellcheck source=runtime.sh
source "$(dirname "${BASH_SOURCE[0]}")/runtime.sh"

container_exists() {
  "${CLI[@]}" container inspect "$DB_CONTAINER" >/dev/null 2>&1
}

container_is_running() {
  [[ "$("${CLI[@]}" inspect --format '{{.State.Status}}' "$DB_CONTAINER" 2>/dev/null)" == "running" ]]
}

ensure_volume() {
  if ! "${CLI[@]}" volume inspect "$DB_VOLUME" >/dev/null 2>&1; then
    log "Creating volume $DB_VOLUME"
    "${CLI[@]}" volume create "$DB_VOLUME" >/dev/null
  fi
}

create_container() {
  log "Creating PostgreSQL container $DB_CONTAINER"
  "${CLI[@]}" run -d \
    --name "$DB_CONTAINER" \
    --restart unless-stopped \
    -e POSTGRES_DB="$DB_NAME" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -p "$DB_PORT:5432" \
    -v "$DB_VOLUME:/var/lib/postgresql/data" \
    --health-cmd='pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    --health-interval=5s \
    --health-timeout=5s \
    --health-retries=20 \
    postgres:16-alpine >/dev/null
}

ensure_container() {
  ensure_volume
  if container_exists; then
    if container_is_running; then
      log "Using existing running container $DB_CONTAINER"
    else
      log "Starting existing container $DB_CONTAINER"
      "${CLI[@]}" start "$DB_CONTAINER" >/dev/null
    fi
  else
    create_container
  fi
}

wait_for_postgres() {
  log "Waiting for PostgreSQL to accept connections"
  for _ in $(seq 1 30); do
    if "${CLI[@]}" exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
}

apply_schema() {
  [[ -f "$SCHEMA_FILE" ]] || { echo "Schema file not found: $SCHEMA_FILE" >&2; exit 1; }
  log "Applying schema from $SCHEMA_FILE"
  "${CLI[@]}" exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$SCHEMA_FILE"
}

apply_base_seed() {
  [[ -f "$BASE_SEED_FILE" ]] || { echo "Base seed file not found: $BASE_SEED_FILE" >&2; exit 1; }
  log "Applying base seed from $BASE_SEED_FILE"
  "${CLI[@]}" exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$BASE_SEED_FILE"
}

apply_test_seed() {
  [[ "$APPLY_TEST_SEED" == "1" ]] || return 0
  if [[ ! -f "$TEST_SEED_FILE" ]]; then
    log "No test seed file found at $TEST_SEED_FILE — skipping"
    return 0
  fi
  log "Applying test seed from $TEST_SEED_FILE"
  "${CLI[@]}" exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$TEST_SEED_FILE"
}

apply_real_seed() {
  [[ "$APPLY_REAL_SEED" == "1" ]] || return 0
  if [[ ! -f "$REAL_SEED_FILE" ]]; then
    log "No real seed file found at $REAL_SEED_FILE — skipping"
    return 0
  fi
  log "Applying real seed from $REAL_SEED_FILE"
  "${CLI[@]}" exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$REAL_SEED_FILE"
}

reset_data() {
  log "Resetting database schema in $DB_NAME"
  "${CLI[@]}" exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" <<SQL
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO "$DB_USER";
GRANT ALL ON SCHEMA public TO public;
SQL
}

open_psql() {
  exec "${CLI[@]}" exec -it "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"
}

stop_container() {
  if container_exists && container_is_running; then
    log "Stopping container $DB_CONTAINER"
    "${CLI[@]}" stop "$DB_CONTAINER" >/dev/null
  else
    log "Container $DB_CONTAINER is not running"
  fi
}

select_runtime

case "$ACTION" in
  up)
    ensure_container
    wait_for_postgres
    apply_schema
    apply_base_seed
    apply_real_seed
    apply_test_seed
    log "Database ready at postgresql://$DB_USER:*****@localhost:$DB_PORT/$DB_NAME"
    ;;
  reset-data)
    ensure_container
    wait_for_postgres
    reset_data
    apply_schema
    apply_base_seed
    apply_real_seed
    apply_test_seed
    log "Database reset at postgresql://$DB_USER:*****@localhost:$DB_PORT/$DB_NAME"
    ;;
  down)
    stop_container
    ;;
  psql)
    ensure_container
    wait_for_postgres
    open_psql
    ;;
  *)
    echo "Usage: $0 {up|reset-data|down|psql}" >&2
    exit 1
    ;;
esac
