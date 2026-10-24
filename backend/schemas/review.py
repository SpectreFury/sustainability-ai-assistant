from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from schemas.extraction import Locator


class ReviewFactUpdate(BaseModel):
    id: UUID
    label: str = Field(min_length=1, max_length=300)
    value_text: str = Field(min_length=1, max_length=2000)

    @field_validator("label", "value_text", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ReviewFactsUpdateRequest(BaseModel):
    facts: list[ReviewFactUpdate] = Field(min_length=1, max_length=2000)

    @field_validator("facts")
    @classmethod
    def unique_fact_ids(cls, facts: list[ReviewFactUpdate]) -> list[ReviewFactUpdate]:
        ids = [fact.id for fact in facts]
        if len(set(ids)) != len(ids):
            raise ValueError("Each fact can only be updated once.")
        return facts


class ReviewFactResponse(BaseModel):
    id: UUID
    key: str
    label: str
    original_label: str
    category: str
    metric: str | None
    series: str | None
    value_text: str
    original_value_text: str
    value_number: str | None
    original_value_number: str | None
    unit: str | None
    period_start: date | None
    period_end: date | None
    note: str | None
    origin: str
    locator: Locator
    quote: str | None
    verified: bool
    verification: str
    derivation: str | None
    edited: bool


class ReviewSegmentResponse(BaseModel):
    ordinal: int
    locator: Locator
    text: str
    cells: dict[str, float | str] | None
    scanned: bool


class DocumentReviewResponse(BaseModel):
    id: UUID
    filename: str
    status: str
    upload_timestamp: datetime
    document_kind: str
    organisation: str | None
    title: str | None
    issuer: str | None
    period_start: date | None
    period_end: date | None
    page_count: int | None
    summary: str | None
    issues: list[str]
    reviewed_at: datetime | None
    reviewed_by: str | None
    file_url: str | None
    facts: list[ReviewFactResponse]
    segments: list[ReviewSegmentResponse]


def decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
