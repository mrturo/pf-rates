"""Root conftest — sets required environment variables before any package import.

Settings() is evaluated eagerly at import time, so env vars that have no default
must be present before the first ``import financial_data`` statement anywhere in
the test suite.  This root-level conftest runs before tests/conftest.py, making
the setup order deterministic without requiring noqa overrides.
"""

import os

# Mandatory field — no insecure in-code default; the test value is harmless.
os.environ.setdefault("FINANCIAL_DATA_API_KEY", "test-key")
