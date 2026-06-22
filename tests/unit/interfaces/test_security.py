"""Unit tests for the API key security dependency."""

import pytest
from fastapi import HTTPException

from financial_data.interfaces.api.security import verify_api_key


def test_verify_api_key_accepts_correct_key() -> None:
    """verify_api_key does not raise when the configured key is provided."""
    verify_api_key("test-key")  # matches FINANCIAL_DATA_API_KEY set in root conftest


def test_verify_api_key_raises_403_when_key_is_absent() -> None:
    """verify_api_key raises HTTP 403 when no key is provided (None)."""
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(None)
    assert exc_info.value.status_code == 403
    assert "Invalid or missing API key" in exc_info.value.detail


def test_verify_api_key_raises_403_on_wrong_key() -> None:
    """verify_api_key raises HTTP 403 when the key does not match."""
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key("not-the-right-key")
    assert exc_info.value.status_code == 403
    assert "Invalid or missing API key" in exc_info.value.detail
