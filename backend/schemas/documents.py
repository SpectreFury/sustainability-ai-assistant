from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints


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
