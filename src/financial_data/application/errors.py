"""Domain-oriented application errors with transport-friendly status codes."""


class FinancialDataError(ValueError):
    """Base application error."""

    status_code = 400


class FinancialDataValidationError(FinancialDataError):
    """Raised for invalid input or malformed commands."""


class FinancialDataNotFoundError(FinancialDataError):
    """Raised when required domain data does not exist."""

    status_code = 404


class FinancialDataDependencyError(FinancialDataError):
    """Raised when configured external providers fail to return required data."""

    status_code = 502


class FinancialDataDependencyConfigurationError(FinancialDataError):
    """Raised when an external dependency is required but not configured."""

    status_code = 503


class ExchangeRateNotFoundError(FinancialDataNotFoundError):
    """Raised when a required exchange rate cannot be found."""


class EconomicIndexNotFoundError(FinancialDataNotFoundError):
    """Raised when a required economic index cannot be found."""


class IncomeTaxBracketNotFoundError(FinancialDataNotFoundError):
    """Raised when no income tax bracket matches the requested period/base."""
