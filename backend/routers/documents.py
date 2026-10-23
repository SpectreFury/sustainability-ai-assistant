from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_user
from db import get_db
from models import User
from schemas.documents import (
    DocumentResponse,
    UploadCompleteRequest,
    UploadFailureRequest,
    UploadSignatureRequest,
    UploadSignatureResponse,
)
from services.document_service import (
    complete_document_upload,
    create_upload_signature,
    fail_document_upload,
    list_user_documents,
    queue_pending_documents,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/upload-signature",
    response_model=UploadSignatureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_signature(
    payload: UploadSignatureRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UploadSignatureResponse:
    return await create_upload_signature(session, user.id, payload)


@router.post(
    "/{document_id}/complete",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
)
async def complete_upload(
    document_id: UUID,
    payload: UploadCompleteRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentResponse:
    return await complete_document_upload(session, user.id, document_id, payload)


@router.post("/{document_id}/failed", response_model=DocumentResponse)
async def upload_failed(
    document_id: UUID,
    payload: UploadFailureRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentResponse:
    return await fail_document_upload(
        session, user.id, document_id, payload.error_message
    )


@router.post(
    "/process",
    response_model=list[DocumentResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_pending_documents(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[DocumentResponse]:
    return await queue_pending_documents(session, user.id)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[DocumentResponse]:
    return await list_user_documents(session, user.id)
