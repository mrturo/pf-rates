# Load .env values (if the file exists) before any ?= defaults so that variables
# defined there take precedence over the empty fallbacks below.
-include .env

# Auto-detected at install time; override with PYTHON=pythonX.Y to pin a specific interpreter.
PYTHON ?= python3.12
VENV ?= .venv
# Auto-detect the correct nerdctl invocation.
# Rancher Desktop routes nerdctl through Docker-managed containerd; the default
# k3s socket is absent on that setup, so we fall back to the Docker socket address.
NERDCTL ?= $(shell nerdctl info >/dev/null 2>&1 && echo "nerdctl" || echo "nerdctl --address /var/run/docker/containerd/containerd.sock")
DB_CONTAINER ?= pf-rates-postgres
DB_VOLUME ?= pf-rates-postgres-data
DB_NAME ?= rates
DB_USER ?= rates
DB_PASSWORD ?= rates
DB_PORT ?= 5433
ADMINER_CONTAINER ?= pf-rates-adminer
ADMINER_PORT ?= 8090
APP_PORT ?= 8001
ENV_FILE ?= .env
VENV_BIN = PATH="$(VENV)/bin:$$PATH"

DB_ENV = NERDCTL_BIN="$(NERDCTL)" DB_CONTAINER="$(DB_CONTAINER)" DB_VOLUME="$(DB_VOLUME)" DB_NAME="$(DB_NAME)" DB_USER="$(DB_USER)" DB_PASSWORD="$(DB_PASSWORD)" DB_PORT="$(DB_PORT)"
DB_SEED_FLAG_base =
DB_SEED_FLAG_test = APPLY_TEST_SEED=1
DB_SEED_FLAG_real = APPLY_REAL_SEED=1
ADMINER_ENV = NERDCTL_BIN="$(NERDCTL)" ADMINER_CONTAINER="$(ADMINER_CONTAINER)" ADMINER_PORT="$(ADMINER_PORT)"
UNSET_PROXY_VARS = bash -eu -o pipefail -c 'vars=(http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY); for v in "$${vars[@]}"; do if [[ -n "$${!v-}" ]]; then printf "  ✓ Unsetting %s → %s\n" "$$v" "$${!v}"; unset "$$v"; else printf "  • %s not set\n" "$$v"; fi; done'

# Corporate registry URLs — set in .env; empty here so .env values take priority.
CORPORATIVE_PIP_INDEX ?=
CORPORATIVE_NPM_REGISTRY ?=
CORPORATIVE_PROXY ?=

# Docker/testcontainers: auto-detect Rancher Desktop socket and disable Ryuk (Ryuk fails on Rancher Desktop)
_RANCHER_SOCK = $(HOME)/.docker/run/docker.sock
_DOCKER_ENV = $(if $(wildcard $(_RANCHER_SOCK)),DOCKER_HOST=unix://$(_RANCHER_SOCK) TESTCONTAINERS_RYUK_DISABLED=true,)

# Creates the local virtual environment and installs project dependencies.
install:
	@python_bin=$$(for v in python3.14 python3.13 python3.12 python3; do \
		if command -v "$$v" >/dev/null 2>&1 && "$$v" -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" 2>/dev/null; then \
			echo "$$v"; break; \
		fi; \
	done); \
	[ -n "$$python_bin" ] || { \
		echo ""; \
		echo "ERROR: Python >=3.12 not found in PATH."; \
		echo ""; \
		echo "  Option 1 — pyenv (recommended if already installed):"; \
		echo "    pyenv install 3.12 && pyenv local 3.12"; \
		echo ""; \
		echo "  Option 2 — install pyenv without brew (works on Corporative VPN):"; \
		echo "    curl -fsSL https://pyenv.run | bash"; \
		echo "    # then add to your shell profile and restart terminal"; \
		echo "    pyenv install 3.12 && pyenv local 3.12"; \
		echo ""; \
		echo "  Option 3 — download installer from https://www.python.org/downloads/"; \
		echo ""; \
		echo "  Then re-run: make reinstall"; \
		echo ""; \
		exit 1; \
	}; \
	echo "  → Using $$python_bin ($$($$python_bin --version))"; \
	"$$python_bin" -m venv "$(VENV)"
	@if curl -sfL --connect-timeout 3 -o /dev/null "$(CORPORATIVE_PIP_INDEX)/" 2>/dev/null; then \
		echo "  → Corporative VPN — routing pip through sysproxy"; \
		printf '[global]\nproxy = $(CORPORATIVE_PROXY)\n' > "$(VENV)/pip.conf"; \
	else \
		echo "  → No VPN — disabling corporate proxy env vars for pip"; \
		printf '[global]\ntrust-env = false\n' > "$(VENV)/pip.conf"; \
	fi
	. "$(VENV)/bin/activate" && python -m pip install -U pip && python -m pip install -e ".[dev]"
	git config core.hooksPath .githooks
	@echo "  ✓ Git hooks configured (.githooks/)"

# Removes all generated artifacts and recreates the virtual environment from scratch.
reinstall: clean
	rm -rf $(VENV)
	@$(MAKE) --no-print-directory install

# Writes a local .env file with database connection and tooling defaults.
env-write:
	@printf 'FINANCIAL_DATA_DATABASE_URL=postgresql+asyncpg://$(DB_USER):$(DB_PASSWORD)@localhost:$(DB_PORT)/$(DB_NAME)\n' > $(ENV_FILE)
	@printf 'FINANCIAL_DATA_API_KEY=change-me-before-use\n' >> $(ENV_FILE)
	@printf '\n# Tooling — corporate pip/npm registries (used by make install/check on VPN)\n' >> $(ENV_FILE)
	@printf 'CORPORATIVE_PIP_INDEX=https://pypi.ci.artifacts.corporative.com/artifactory/api/pypi/pythonhosted-pypi-release-remote/simple\n' >> $(ENV_FILE)
	@printf 'CORPORATIVE_NPM_REGISTRY=https://npm.ci.artifacts.corporative.com/artifactory/api/npm/external-npm\n' >> $(ENV_FILE)
	@printf 'CORPORATIVE_PROXY=http://sysproxy.corporative.com:8080\n' >> $(ENV_FILE)
	@printf '\n# Rate provider HTTP proxy (optional — leave unset for direct connections).\n' >> $(ENV_FILE)
	@printf '# Set to the corporate proxy when the external APIs are only reachable via VPN proxy.\n' >> $(ENV_FILE)
	@printf '#FINANCIAL_DATA_HTTP_PROXY=http://proxy.corpo-rative.com:8080\n' >> $(ENV_FILE)
	@echo "  ✓ $(ENV_FILE) written"

# Internal: run scripts/db.sh with a selected action and optional seed mode.
_db-flow:
	$(DB_ENV) $(DB_SEED_FLAG_$(SEED_MODE)) ./scripts/db.sh $(DB_ACTION)

# Starts PostgreSQL with the base schema and seed data.
db-up:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=up SEED_MODE=base

# Starts PostgreSQL and also loads test fixtures.
db-up-test:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=up SEED_MODE=test

# Starts PostgreSQL and also loads real operational seed data.
db-up-real:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=up SEED_MODE=real

# Recreates the schema and reloads only base seed data.
db-reset-data:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=reset-data SEED_MODE=base

# Recreates the schema and reloads base + test seed data.
db-reset-data-test:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=reset-data SEED_MODE=test

# Recreates the schema and reloads base + real operational seed data.
db-reset-data-real:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=reset-data SEED_MODE=real

# Stops and removes the PostgreSQL container.
db-down:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=down SEED_MODE=base

# Stops PostgreSQL (if running) and starts it again with the base schema and seed data.
db-restart: db-down db-up

# Opens an interactive psql session inside the PostgreSQL container.
db-psql:
	$(MAKE) --no-print-directory _db-flow DB_ACTION=psql SEED_MODE=base

# Starts Adminer after ensuring PostgreSQL is up.
adminer-up: db-up
	$(ADMINER_ENV) ./scripts/adminer.sh up

# Stops and removes the Adminer container.
adminer-down: db-down
	$(ADMINER_ENV) ./scripts/adminer.sh down

# Stops Adminer (if running) and starts it again — does not restart the database.
adminer-restart:
	-$(ADMINER_ENV) ./scripts/adminer.sh down
	$(ADMINER_ENV) ./scripts/adminer.sh up

# Unsets common proxy variables in the current shell invocation.
unset-proxy-vars:
	@$(UNSET_PROXY_VARS)

# Brings up the full local stack (DB, Adminer, env, deps, and API).
local-up:
	$(DB_ENV) $(ADMINER_ENV) \
		APP_PORT="$(APP_PORT)" \
		VENV="$(VENV)" ENV_FILE="$(ENV_FILE)" \
		CORPORATIVE_PIP_INDEX="$(CORPORATIVE_PIP_INDEX)" \
		CORPORATIVE_NPM_REGISTRY="$(CORPORATIVE_NPM_REGISTRY)" \
		./scripts/local_stack.sh

# Runs the FastAPI server in development mode with auto-reload.
run:
	$(VENV_BIN) uvicorn financial_data.interfaces.api.app:app --reload --port $(APP_PORT)

# Scans filesystem for misconfigurations and secrets (no network DB required).
# Vulnerability scanning is handled by trivy image in the CI build job.
security-scan:
	trivy fs --scanners misconfig,secret --severity HIGH,CRITICAL --exit-code 1 --skip-files '.env' --skip-version-check .

# Runs the complete test suite.
test:
	$(_DOCKER_ENV) $(VENV_BIN) pytest

# Runs the test suite with coverage and enforces 100% coverage.
test-cov:
	$(_DOCKER_ENV) $(VENV_BIN) pytest --cov=src --cov-report=term-missing --cov-fail-under=100

# Executes all repository quality gates in sequence.
check:
	@set -e; \
	for target in lint dead-code typecheck duplicate-code-src duplicate-code-tests duplicate-code test test-cov security-scan; do \
		echo "==> make $$target"; \
		if ! $(MAKE) --no-print-directory $$target; then \
			echo "FAILED: $$target"; \
			exit 1; \
		fi; \
	done; \
	echo "All checks passed."

# Detects duplicated code across the entire repository (all languages, cross-boundary clones included).
duplicate-code:
	$(MAKE) --no-print-directory _duplicate-code DUPLICATE_PATH=. DUPLICATE_THRESHOLD=0

# Detects duplicated code in tests only.
duplicate-code-tests:
	$(MAKE) --no-print-directory _duplicate-code DUPLICATE_PATH=tests DUPLICATE_THRESHOLD=0

# Detects duplicated code in src only.
duplicate-code-src:
	$(MAKE) --no-print-directory _duplicate-code DUPLICATE_PATH=src DUPLICATE_THRESHOLD=0

# Runs jscpd with configurable path and threshold.
_duplicate-code:
	@if curl -sfL --connect-timeout 2 -o /dev/null "$(CORPORATIVE_NPM_REGISTRY)/" 2>/dev/null; then \
		echo "  → Corporative VPN detected — using Artifactory npm registry"; \
		export npm_config_registry="$(CORPORATIVE_NPM_REGISTRY)"; \
	fi; \
	npx --yes jscpd --mode strict --min-lines 10 --min-tokens 70 --threshold $(DUPLICATE_THRESHOLD) --reporters console --ignore "**/.venv/**,**/build/**,**/dist/**,**/.github/**" $(DUPLICATE_PATH)

# Runs Ruff autofixes/formatting and then validates lint cleanliness.
lint:
	$(VENV_BIN) ruff check --fix --exit-zero src tests
	$(VENV_BIN) ruff format src tests
	$(VENV_BIN) ruff check src tests

# Reports potentially unused code via Vulture.
dead-code:
	$(VENV_BIN) vulture --config pyproject.toml

# Runs static type checking with mypy.
typecheck:
	$(VENV_BIN) mypy --install-types --non-interactive src

# Installs Python 3.12 via pyenv (installs pyenv first if not found). Works on Corporative VPN.
install-python:
	@if command -v pyenv >/dev/null 2>&1; then \
		echo "  → pyenv found, installing Python 3.12..."; \
		pyenv install -s 3.12; \
		pyenv local 3.12; \
		echo "  ✓ Python 3.12 ready. Re-run: make reinstall"; \
	else \
		echo "  → pyenv not found, installing via https://pyenv.run ..."; \
		curl -fsSL https://pyenv.run | bash; \
		echo ""; \
		echo "  ✓ pyenv installed. Add the following to your shell profile (~/.zshrc or ~/.bashrc),"; \
		echo "    restart your terminal, then run: make install-python"; \
		echo ""; \
		echo '    export PYENV_ROOT="$$HOME/.pyenv"'; \
		echo '    export PATH="$$PYENV_ROOT/bin:$$PATH"'; \
		echo '    eval "$$(pyenv init -)"'; \
	fi

# Removes local caches, build artifacts, and generated output files.
clean:
	rm -rf .coverage htmlcov .pytest_cache .mypy_cache .ruff_cache build dist
	rm -f .coverage.* .dmypy.json dmypy.json
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
