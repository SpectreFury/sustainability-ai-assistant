from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from dependencies.auth import get_current_user
from models import User
from schemas.financial_year import FinancialYearSummaryResponse
from services.financial_year_service import get_financial_year_summary

router = APIRouter(prefix="/financial-year", tags=["financial year"])


@router.get("/summary", response_model=FinancialYearSummaryResponse)
async def financial_year_summary(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    financial_year: str | None = None,
    organisation: str | None = None,
    document_ids: Annotated[list[UUID] | None, Query()] = None,
    document_scope: Literal["all", "selected"] = "all",
) -> FinancialYearSummaryResponse:
    return await get_financial_year_summary(
        session,
        user.id,
        financial_year,
        organisation,
        document_ids,
        document_scope == "selected",
    )
