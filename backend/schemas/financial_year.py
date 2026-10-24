from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from schemas.extraction import Locator


class FinancialYearOption(BaseModel):
    value: str
    label: str


class FinancialYearOrganisationOption(BaseModel):
    value: str
    label: str


class FinancialYearDocumentOption(BaseModel):
    id: UUID
    filename: str
    status: str
    organisation: str | None
    has_successful_extraction: bool
    selected: bool


class FinancialYearMonth(BaseModel):
    label: str
    covered: bool
    value: str | None


class FinancialYearMetric(BaseModel):
    metric: str
    label: str
    series: str | None
    unit: str | None
    value: str | None
    status: Literal["reported", "calculated", "no_data", "conflict"]
    period_label: str
    method: str
    calculation: str | None
    months_covered: int
    months: list[FinancialYearMonth]
    source_document_ids: list[UUID]
    note: str | None = None


class FinancialYearSource(BaseModel):
    fact_id: UUID
    document_id: UUID
    filename: str
    label: str
    metric: str | None
    series: str | None
    unit: str | None
    value: str
    value_text: str
    period_start: date | None
    period_end: date | None
    locator: Locator
    quote: str | None
    verified: bool
    treatment: Literal["primary", "corroboration", "excluded", "supporting"]
    reason: str


class FinancialYearExcludedDocument(BaseModel):
    id: UUID
    filename: str
    organisation: str | None
    status: str
    reason: str


class FinancialYearSummaryResponse(BaseModel):
    financial_year: str
    financial_year_start: date
    financial_year_end: date
    financial_year_options: list[FinancialYearOption]
    organisation: str | None
    organisation_options: list[FinancialYearOrganisationOption]
    documents: list[FinancialYearDocumentOption]
    selected_document_ids: list[UUID]
    primary_source_count: int
    corroborating_source_count: int
    coverage_status: Literal["complete", "partial", "no_data"]
    metrics: list[FinancialYearMetric]
    sources: list[FinancialYearSource]
    excluded_documents: list[FinancialYearExcludedDocument]
    gaps: list[str]
