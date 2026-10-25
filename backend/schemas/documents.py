from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)


_SAFE_DOCUMENT_ERROR_PREFIXES = (
    "The upload has not completed",
    "Unsupported file type",
    "Could not submit this job to the worker queue",
    "A temporary processing issue",
    "This PDF is password-protected",
    "The uploaded file is empty",
    "The uploaded document is empty",
    "File verification failed",
    "Document extraction is not configured",
    "No supported information",
    "No verifiable information",
    "This document exceeds",
    "Only PDF and XLSX documents",
    "The uploaded document could not be retrieved",
    "Document processing failed",
    "The upload failed",
    "Could not enqueue a retry",
)


def sanitize_document_error(value: str | None) -> str | None:
    if value is None:
        return None
    if any(value.startswith(prefix) for prefix in _SAFE_DOCUMENT_ERROR_PREFIXES):
        return value[:500]
    return "Document processing failed. Please try again or contact support."


class UploadSignatureRequest(BaseModel):
    filename: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ]
    file_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class UploadSignatureResponse(BaseModel):
    document_id: UUID
    upload_url: str
    cloud_name: str
    api_key: str
    timestamp: int
    public_id: str
    signature: str


class UploadCompleteRequest(BaseModel):
    cloudinary_url: AnyHttpUrl
    cloudinary_public_id: str


class UploadFailureRequest(BaseModel):
    error_message: str = Field(min_length=1, max_length=2000)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: int
    filename: str
    cloudinary_url: str | None
    cloudinary_public_id: str
    status: str
    error_message: str | None
    upload_timestamp: datetime
    chunks_completed: int | None = None
    chunks_total: int | None = None

    @field_validator("error_message", mode="before")
    @classmethod
    def hide_internal_errors(cls, value: str | None) -> str | None:
        return sanitize_document_error(value)
