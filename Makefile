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
APP_PORT ?= 8001
ENV_FILE ?= .env
VENV_BIN = PATH="$(VENV)/bin:$$PATH"

DB_ENV = NERDCTL_BIN="$(NERDCTL)" DB_CONTAINER="$(DB_CONTAINER)" DB_VOLUME="$(DB_VOLUME)" DB_NAME="$(DB_NAME)" DB_USER="$(DB_USER)" DB_PASSWORD="$(DB_PASSWORD)" DB_PORT="$(DB_PORT)"

WALMART_PIP_INDEX ?= https://pypi.ci.artifacts.walmart.com/artifactory/api/pypi/pythonhosted-pypi-release-remote/simple
WALMART_NPM_REGISTRY ?= https://npm.ci.artifacts.walmart.com/artifactory/api/npm/external-npm

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
	  echo "  Option 2 — install pyenv without brew (works on Walmart VPN):"; \
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
	@if curl -sfL --connect-timeout 3 -o /dev/null "$(WALMART_PIP_INDEX)/" 2>/dev/null; then \
	  echo "  → Walmart VPN — routing pip through sysproxy"; \
	  printf '[global]\nproxy = http://sysproxy.wal-mart.com:8080\n' > "$(VENV)/pip.conf"; \
	else \
	  echo "  → No VPN — disabling corporate proxy env vars for pip"; \
	  printf '[global]\ntrust-env = false\n' > "$(VENV)/pip.conf"; \
	fi
	. "$(VENV)/bin/activate" && python -m pip install -U pip && python -m pip install -e ".[dev]"

# Removes all generated artifacts and recreates the virtual environment from scratch.
reinstall: clean
	rm -rf $(VENV)
	@$(MAKE) --no-print-directory install

# Writes a local .env file with database connection defaults.
env-write:
	@printf 'FINANCIAL_DATA_DATABASE_URL=postgresql+asyncpg://$(DB_USER):$(DB_PASSWORD)@localhost:$(DB_PORT)/$(DB_NAME)\n' > $(ENV_FILE)
	@echo "  ✓ $(ENV_FILE) written"

# Starts the PostgreSQL container and applies schema + seed.
db-up:
	$(NERDCTL) run -d \
	  --name $(DB_CONTAINER) \
	  -e POSTGRES_USER=$(DB_USER) \
	  -e POSTGRES_PASSWORD=$(DB_PASSWORD) \
	  -e POSTGRES_DB=$(DB_NAME) \
	  -p $(DB_PORT):5432 \
	  -v $(DB_VOLUME):/var/lib/postgresql/data \
	  postgres:16-alpine || true
	@sleep 2
	$(NERDCTL) exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) < db/01_schema.sql
	$(NERDCTL) exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) < db/02_seed_currencies.sql
	@echo "  ✓ Database ready"

# Stops and removes the PostgreSQL container.
db-down:
	$(NERDCTL) rm -f $(DB_CONTAINER) || true

# Opens an interactive psql session inside the PostgreSQL container.
db-psql:
	$(NERDCTL) exec -it $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME)

# Runs the FastAPI server in development mode with auto-reload.
run: env-write
	$(VENV_BIN) uvicorn financial_data.interfaces.api.app:app --reload --port $(APP_PORT)

# Runs the complete test suite.
test:
	$(_DOCKER_ENV) $(VENV_BIN) pytest

# Runs the test suite with coverage and enforces 100% coverage.
test-cov:
	$(_DOCKER_ENV) $(VENV_BIN) pytest --cov=src --cov-report=term-missing --cov-fail-under=100

# Executes all repository quality gates in sequence.
check:
	@set -e; \
	for target in lint dead-code typecheck duplicate-code-src duplicate-code-tests test test-cov; do \
		echo "==> make $$target"; \
		if ! $(MAKE) --no-print-directory $$target; then \
			echo "FAILED: $$target"; \
			exit 1; \
		fi; \
	done; \
	echo "All checks passed."

# Detects duplicated code in tests with a 10% threshold.
duplicate-code-tests:
	$(MAKE) --no-print-directory _duplicate-code DUPLICATE_PATH=tests DUPLICATE_THRESHOLD=10

# Detects duplicated code in src with a 1% threshold.
duplicate-code-src:
	$(MAKE) --no-print-directory _duplicate-code DUPLICATE_PATH=src DUPLICATE_THRESHOLD=1

# Runs jscpd with configurable path and threshold.
_duplicate-code:
	@if curl -sfL --connect-timeout 2 -o /dev/null "$(WALMART_NPM_REGISTRY)/" 2>/dev/null; then \
	  echo "  → Walmart VPN detected — using Artifactory npm registry"; \
	  export npm_config_registry="$(WALMART_NPM_REGISTRY)"; \
	fi; \
	npx --yes jscpd --mode strict --min-lines 10 --min-tokens 70 --threshold $(DUPLICATE_THRESHOLD) --reporters console --ignore "**/.venv/**,**/build/**,**/dist/**" $(DUPLICATE_PATH)

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

# Installs Python 3.12 via pyenv (installs pyenv first if not found). Works on Walmart VPN.
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
