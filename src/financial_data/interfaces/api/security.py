"""API key security dependency."""

import secrets
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from financial_data.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    key: Annotated[str | None, Security(_api_key_header)] = None,
) -> None:
    """Verify the X-API-Key header against the configured key.

    Raises HTTP 403 if the header is absent or does not match.
    Uses a timing-safe comparison to prevent timing-based key enumeration.
    """
    if key is None or not secrets.compare_digest(key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key.",
        )
