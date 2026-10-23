from typing import Annotated

from fastapi import APIRouter, Depends

from dependencies.auth import get_current_user
from models import User
from schemas.documents import UploadSignatureResponse
from services.document_service import create_upload_signature

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload-signature", response_model=UploadSignatureResponse)
async def upload_signature(
    user: Annotated[User, Depends(get_current_user)],
) -> UploadSignatureResponse:
    return create_upload_signature(user.id)
