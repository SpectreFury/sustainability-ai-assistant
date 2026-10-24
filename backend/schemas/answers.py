from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from schemas.extraction import Locator

AnswerStatus = Literal[
    "answered",
    "partial",
    "insufficient_evidence",
    "conflicting_evidence",
]


class AnswerRequest(BaseModel):
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=2000),
    ]
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("document_ids")
    @classmethod
    def unique_document_ids(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


class AnswerEvidenceDraft(BaseModel):
    id: str = Field(pattern=r"^E[1-9][0-9]{0,2}$")
    document_id: UUID
    page: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    quote: str = Field(min_length=1, max_length=4000)


class AnswerClaimDraft(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    calculation_ids: list[str] = Field(default_factory=list, max_length=50)


class AnswerKeyValueDraft(BaseModel):
    label: str = Field(min_length=1, max_length=300)
    value: str | None = None
    value_text: str = Field(min_length=1, max_length=300)
    unit: str | None = Field(default=None, max_length=100)
    period: str | None = Field(default=None, max_length=200)
    origin: Literal["reported", "calculated"]
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_id: str | None = None

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = Decimal(value.replace(",", "").strip())
        except InvalidOperation as error:
            raise ValueError("Answer values must be decimal strings") from error
        if not parsed.is_finite():
            raise ValueError("Answer values must be finite decimals")
        return format(parsed, "f")


class AnswerCalculationDraft(BaseModel):
    id: str = Field(pattern=r"^C[1-9][0-9]{0,2}$")
    description: str = Field(min_length=1, max_length=500)
    expression: str = Field(min_length=1, max_length=5000)
    result: str = Field(min_length=1, max_length=100)
    unit: str | None = Field(default=None, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("result")
    @classmethod
    def finite_result(cls, value: str) -> str:
        try:
            parsed = Decimal(value.replace(",", "").strip())
        except InvalidOperation as error:
            raise ValueError("Calculation results must be decimal strings") from error
        if not parsed.is_finite():
            raise ValueError("Calculation results must be finite decimals")
        return format(parsed, "f")


class AnswerToolCallDraft(BaseModel):
    name: Literal["calculate", "financial_year_totals"]
    expression: str = Field(default="", max_length=5000)
    financial_year: str = Field(default="", max_length=32)
    metric: str = Field(default="", max_length=32)
    document_id: str = Field(default="", max_length=36)


class AnswerDraft(BaseModel):
    status: AnswerStatus
    # `answer` remains for compatibility with persisted/legacy drafts. New model
    # responses provide claims; the server renders their citations.
    answer: str = Field(min_length=1, max_length=12000)
    claims: list[AnswerClaimDraft] = Field(default_factory=list, max_length=100)
    key_values: list[AnswerKeyValueDraft] = Field(default_factory=list, max_length=100)
    calculations: list[AnswerCalculationDraft] = Field(default_factory=list, max_length=50)
    evidence: list[AnswerEvidenceDraft] = Field(default_factory=list, max_length=100)
    gaps: list[str] = Field(default_factory=list, max_length=50)
    tool_calls: list[AnswerToolCallDraft] = Field(default_factory=list, max_length=12)


class AnswerKeyValue(BaseModel):
    label: str
    value: str | None
    value_text: str
    unit: str | None
    period: str | None
    origin: Literal["reported", "calculated"]
    evidence_ids: list[str]
    calculation_id: str | None
    verified: bool
    verification: str


class AnswerCalculation(BaseModel):
    id: str
    description: str
    expression: str
    result: str
    computed: str | None
    matches: bool
    unit: str | None
    evidence_ids: list[str]
    verification: str


class AnswerEvidence(BaseModel):
    id: str
    document_id: UUID
    filename: str
    locator: Locator
    locator_label: str
    quote: str
    source_preview: str
    verified: bool
    verification: str


class AnswerContent(BaseModel):
    answer: str
    key_values: list[AnswerKeyValue]
    calculations: list[AnswerCalculation]
    evidence: list[AnswerEvidence]
    gaps: list[str]
    model: str


class AnswerRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    question: str
    document_ids: list[UUID]
    status: AnswerStatus
    answer: AnswerContent
    created_at: datetime
