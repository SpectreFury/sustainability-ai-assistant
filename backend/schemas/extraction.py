from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


DocType = Literal[
    "electricity_bill",
    "water_bill",
    "consumption_workbook",
    "waste_record",
    "policy",
    "other",
]

FactCategory = Literal[
    "consumption",
    "meter_reading",
    "amount",
    "quantity",
    "period",
    "date",
    "identifier",
    "rate",
    "scope",
    "commitment",
    "party",
    "other",
]

Metric = Literal["electricity", "water", "waste", "fuel", "emissions", "cost", "other"]


class Locator(BaseModel):
    """A PDF page or spreadsheet range that locates source material."""

    page: int | None = None
    sheet: str | None = None
    cell_range: str | None = None

    def label(self) -> str:
        if self.sheet:
            return f"{self.sheet}!{self.cell_range}" if self.cell_range else self.sheet
        return f"p.{self.page}" if self.page else "document"


class Segment(BaseModel):
    """Citable source text: one PDF page or a block of spreadsheet rows."""

    ordinal: int
    locator: Locator
    text: str
    cells: dict[str, float | str] | None = None
    scanned: bool = False


class SourceOut(BaseModel):
    page: int | None = Field(description="1-based PDF page number; null for spreadsheets")
    sheet: str | None = Field(description="Spreadsheet sheet name; null for PDFs")
    cell_range: str | None = Field(description="A1-style cell or range; null for PDFs")
    quote: str = Field(description="Verbatim text at the cited location that supports the fact")


class FactOut(BaseModel):
    key: str = Field(description="Stable snake_case identifier for this fact")
    label: str = Field(description="Short human-readable label grounded in the document")
    category: FactCategory
    metric: Metric | None = Field(
        default=None, description="What the value measures, when applicable"
    )
    series: str | None = Field(
        default=None, description="Shared name for repeated values in a series"
    )
    value_text: str = Field(description="Value as written in the source, including unit/currency")
    value_number: float | None = Field(
        default=None, description="Numeric value without separators, if numeric"
    )
    unit: str | None = Field(
        default=None, description="Unit or currency as printed or explicitly assumed"
    )
    period_start: str | None = Field(
        default=None, description="ISO date at the start of the covered period"
    )
    period_end: str | None = Field(
        default=None, description="ISO date at the end of the covered period"
    )
    note: str | None = Field(default=None, description="Qualifiers, assumptions, or ambiguity")
    source: SourceOut


class ExtractionOut(BaseModel):
    doc_type: DocType
    title: str = Field(description="What the document is, in a few words")
    organisation: str | None = Field(
        default=None, description="The customer/reporting organisation, if stated"
    )
    issuer: str | None = Field(
        default=None, description="The issuing utility or authority, if stated"
    )
    period_start: str | None = Field(
        default=None, description="ISO start date of the main period covered"
    )
    period_end: str | None = Field(
        default=None, description="ISO end date of the main period covered"
    )
    summary: str = Field(description="Two-sentence summary of the document contents")
    facts: list[FactOut]
    issues: list[str] = Field(description="Contradictions, missing values, or ambiguities to review")


class Fact(BaseModel):
    """Validated extraction fact stored and returned by the application."""

    key: str
    label: str
    category: FactCategory
    metric: Metric | None = None
    series: str | None = None
    value_text: str
    value_number: Decimal | None = None
    unit: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    note: str | None = None
    origin: Literal["reported", "calculated"] = "reported"
    locator: Locator
    quote: str | None = None
    verified: bool = False
    verification: str = ""
    derivation: str | None = None


class Extraction(BaseModel):
    doc_type: DocType
    title: str
    organisation: str | None = None
    issuer: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    summary: str
    page_count: int | None = None
    facts: list[Fact]
    issues: list[str]
    segments: list[Segment]
    model: str
    pipeline: str
