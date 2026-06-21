# ── builder stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip --no-cache-dir

# Install runtime dependencies only (no [dev] extras).
# Regular (non-editable) install places the package in venv/site-packages,
# so the final stage does not need to carry the src/ tree.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# ── final stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Runtime: installed package + alembic migration files
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

# Cloud Run injects PORT at runtime; default to 8080 for local runs.
# Uses shell form (via sh -c) to allow ${PORT:-8080} variable expansion
# while properly forwarding OS signals via exec.
ENTRYPOINT ["sh", "-c"]
CMD ["exec uvicorn financial_data.interfaces.api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
