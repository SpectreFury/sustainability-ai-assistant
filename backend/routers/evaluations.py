import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from dependencies.auth import get_current_user
from models import EvaluationRun, User
from schemas.evaluations import (
    EvaluationCaseResponse,
    EvaluationRunCreated,
    EvaluationRunResponse,
    EvaluationRunSummary,
)
from services.evaluation_service import (
    case_catalog,
    create_evaluation_run,
    get_evaluation_run,
    list_evaluation_runs,
    serialize_run,
    serialize_run_summary,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
logger = logging.getLogger(__name__)


@router.get("/cases", response_model=list[EvaluationCaseResponse])
async def list_cases(
    user: Annotated[User, Depends(get_current_user)],
) -> list[dict]:
    del user
    return case_catalog()


@router.post(
    "/runs",
    response_model=EvaluationRunCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EvaluationRunCreated:
    run = await create_evaluation_run(session, user.id)
    publish_started = perf_counter()
    try:
        from workers.evaluation import process_evaluation

        await process_evaluation.kiq(str(run.id))
    except Exception as error:
        logger.exception(
            "event=task_publish_failed task=evaluation run_id=%s error_type=%s",
            run.id,
            type(error).__name__,
        )
        await session.rollback()
        persisted_run = await session.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.id == run.id, EvaluationRun.user_id == user.id)
            .with_for_update()
        )
        if persisted_run is not None and persisted_run.status == "queued":
            persisted_run.status = "failed"
            persisted_run.current_stage = "Queue failed"
            persisted_run.completed_at = datetime.now(UTC)
            persisted_run.error_message = (
                "Could not submit this evaluation to Redis. Check Redis and try again."
            )
            await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not submit the evaluation job. Check Redis and try again.",
        ) from error

    logger.info(
        "event=task_dispatched task=evaluation run_id=%s queue_publish_ms=%s",
        run.id,
        int((perf_counter() - publish_started) * 1000),
    )
    await session.refresh(run)
    return EvaluationRunCreated.model_validate(run)


@router.get("/runs", response_model=list[EvaluationRunSummary])
async def list_runs(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict]:
    runs = await list_evaluation_runs(session, user.id, limit)
    return [serialize_run_summary(run) for run in runs]


@router.get("/runs/{run_id}", response_model=EvaluationRunResponse)
async def read_run(
    run_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    run = await get_evaluation_run(session, user.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return serialize_run(run)
