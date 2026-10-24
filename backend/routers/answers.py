from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from dependencies.auth import get_current_user
from models import User
from schemas.answers import AnswerRecordResponse, AnswerRequest
from services.answer_service import (
    AnswerGenerationError,
    AnswerModelNotConfigured,
    AnswerRequestError,
    create_answer,
    list_user_answers,
)

router = APIRouter(prefix="/answers", tags=["answers"])


@router.post(
    "",
    response_model=AnswerRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ask_question(
    payload: AnswerRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AnswerRecordResponse:
    try:
        return await create_answer(
            session,
            user.id,
            payload.question,
            payload.document_ids,
        )
    except AnswerRequestError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=str(error),
        ) from error
    except AnswerModelNotConfigured as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except AnswerGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The answer could not be generated. Please try again.",
        ) from error


@router.get("", response_model=list[AnswerRecordResponse])
async def answer_history(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[AnswerRecordResponse]:
    return await list_user_answers(session, user.id, limit)
