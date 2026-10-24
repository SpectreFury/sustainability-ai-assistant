from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


EvaluationRunStatus = Literal["queued", "running", "completed", "failed"]


class EvaluationCaseResponse(BaseModel):
    id: str
    title: str
    question: str
    domain: str
    runner: str
    required_documents: list[str]
    expected_status: str
    expected_evidence: list[dict[str, Any]]


class EvaluationRunSummary(BaseModel):
    id: UUID
    status: EvaluationRunStatus
    current_stage: str | None
    case_set_version: str
    model_name: str | None
    case_count: int
    completed_count: int
    passed_count: int
    evaluated_count: int
    blocked_count: int
    error_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class EvaluationRunResponse(EvaluationRunSummary):
    case_set_hash: str
    answer_prompt_hash: str
    extraction_prompt_hash: str
    document_snapshot: dict[str, Any]
    case_results: list[dict[str, Any]]


class EvaluationRunCreated(BaseModel):
    id: UUID
    status: EvaluationRunStatus
    current_stage: str | None
    case_set_version: str
    case_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
