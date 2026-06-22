"""Income tax bracket routes."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from financial_data.application.dto import (
    IncomeTaxBracketDTO,
    RefreshIncomeTaxBracketsCommandDTO,
)
from financial_data.application.errors import (
    FinancialDataError,
    IncomeTaxBracketNotFoundError,
)
from financial_data.application.ports.reference_data_repository import (
    ReferenceDataRepository,
)
from financial_data.application.use_cases.refresh_income_tax_brackets import (
    RefreshIncomeTaxBrackets,
)
from financial_data.interfaces.api.dependencies import (
    get_reference_data_repository,
    get_refresh_income_tax_brackets_use_case,
)
from financial_data.interfaces.api.errors import to_http_exception

router = APIRouter(prefix="/income-tax-brackets", tags=["income-tax-brackets"])


class IncomeTaxBracketRead(BaseModel):
    """Represent Income Tax Bracket Read."""

    valid_from: date
    valid_to: date | None
    lower_bound_utm: str
    upper_bound_utm: str | None
    marginal_rate: str
    rebate_utm: str


class RefreshIncomeTaxBracketsRequest(BaseModel):
    """Represent Refresh Income Tax Brackets Request."""

    year: int = Field(ge=1990, le=2100)


class RefreshIncomeTaxBracketsResponse(BaseModel):
    """Represent Refresh Income Tax Brackets Response."""

    upserted: int


def _to_bracket_read(bracket: IncomeTaxBracketDTO) -> IncomeTaxBracketRead:
    """Convert a bracket DTO to its API read model."""
    return IncomeTaxBracketRead(
        valid_from=bracket.valid_from,
        valid_to=bracket.valid_to,
        lower_bound_utm=str(bracket.lower_bound_utm),
        upper_bound_utm=str(bracket.upper_bound_utm)
        if bracket.upper_bound_utm is not None
        else None,
        marginal_rate=str(bracket.marginal_rate),
        rebate_utm=str(bracket.rebate_utm),
    )


@router.get("", response_model=IncomeTaxBracketRead)
async def get_income_tax_bracket(
    reference_date: date = Query(...),
    taxable_base_utm: Decimal = Query(...),
    repository: ReferenceDataRepository = Depends(get_reference_data_repository),
) -> IncomeTaxBracketRead:
    """Return the bracket matching the reference date and taxable base in UTM."""
    bracket = await repository.get_income_tax_bracket(reference_date, taxable_base_utm)
    if bracket is None:
        raise to_http_exception(
            IncomeTaxBracketNotFoundError(
                f"No income tax bracket found for reference_date={reference_date} "
                f"and taxable_base_utm={taxable_base_utm}."
            )
        )
    return _to_bracket_read(bracket)


@router.get("/list", response_model=list[IncomeTaxBracketRead])
async def list_income_tax_brackets(
    year: int = Query(...),
    repository: ReferenceDataRepository = Depends(get_reference_data_repository),
) -> list[IncomeTaxBracketRead]:
    """List income tax brackets for the given year."""
    return [
        _to_bracket_read(bracket)
        for bracket in await repository.list_income_tax_brackets(year)
    ]


@router.post("/refresh", response_model=RefreshIncomeTaxBracketsResponse)
async def refresh_income_tax_brackets(
    payload: RefreshIncomeTaxBracketsRequest,
    use_case: RefreshIncomeTaxBrackets = Depends(
        get_refresh_income_tax_brackets_use_case
    ),
) -> RefreshIncomeTaxBracketsResponse:
    """Fetch and persist official income tax brackets for the given year."""
    try:
        result = await use_case.execute(
            RefreshIncomeTaxBracketsCommandDTO(year=payload.year)
        )
    except FinancialDataError as exc:
        raise to_http_exception(exc) from exc
    return RefreshIncomeTaxBracketsResponse(upserted=result.upserted_brackets)
