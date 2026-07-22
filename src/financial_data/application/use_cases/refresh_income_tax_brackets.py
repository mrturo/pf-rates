"""Use case for synchronizing official monthly income tax brackets."""

from financial_data.application.errors import FinancialDataDependencyError
from financial_data.application.dto import (
    RefreshIncomeTaxBracketsCommandDTO,
    RefreshIncomeTaxBracketsResultDTO,
)
from financial_data.application.ports.rate_provider import IncomeTaxBracketProvider
from financial_data.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)


class RefreshIncomeTaxBrackets:
    """Fetch and persist official monthly income tax brackets for a given year."""

    def __init__(
        self,
        repository: ReferenceDataRepository,
        provider: IncomeTaxBracketProvider,
    ) -> None:
        """Initialize the instance."""
        self._repository = repository
        self._provider = provider

    async def execute(
        self,
        command: RefreshIncomeTaxBracketsCommandDTO,
    ) -> RefreshIncomeTaxBracketsResultDTO:
        """Handle execute."""
        brackets = await self._provider.fetch_income_tax_brackets(command.year)
        if not brackets:
            raise FinancialDataDependencyError(
                f"No official income tax brackets were found for {command.year}."
            )

        upserted_brackets = await self._repository.upsert_income_tax_brackets(brackets)
        refreshed_months = len({item.valid_from for item in brackets})
        return RefreshIncomeTaxBracketsResultDTO(
            year=command.year,
            refreshed_months=refreshed_months,
            upserted_brackets=upserted_brackets,
        )
