"""Helpers for mapping application errors to HTTP responses."""

from fastapi import HTTPException

from financial_data.application.errors import FinancialDataError


def to_http_exception(
    exc: FinancialDataError, *, default_status: int = 400
) -> HTTPException:
    """Convert application errors into HTTP exceptions."""
    status_code = (
        exc.status_code if isinstance(exc, FinancialDataError) else default_status
    )
    return HTTPException(status_code=status_code, detail=str(exc))
