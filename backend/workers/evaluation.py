"""Durable end-to-end evaluation worker for the source-backed case pack."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from broker import broker
from db import SessionLocal
from evaluations.case_pack import EVALUATION_CASES, case_set_hash, public_case
from models import Document, EvaluationRun, ExtractionRun
from prompts.answer import ANSWER_INSTRUCTIONS
from prompts.fact_extraction import FACT_EXTRACTION_INSTRUCTIONS
from schemas.extraction import Extraction
from schemas.answers import AnswerContent
from services.answer_service import (
    AnswerDocument,
    answer_model_name,
    generate_answer_for_documents,
)
from services.errors import TemporaryExtractionError
from services.evaluation_service import (
    score_case,
    score_extraction_diagnostics,
    score_financial_year_summary,
)
from services.extraction import download_document, extract_document
from services.extraction_queue import MAX_EXTRACTION_ATTEMPTS, retry_delay_seconds
from services.financial_year_service import get_financial_year_summary
from utils.worker_logging import configure_worker_logging

logger = logging.getLogger(__name__)
_WORKER_LEASE_SECONDS = 300
_HEARTBEAT_SECONDS = 30
_MAX_ANSWER_ATTEMPTS = 3

if broker.is_worker_process:
    configure_worker_logging()
    logger.info("Worker task registered | task=evaluation")


class _EvaluationLeaseLost(RuntimeError):
    """Another worker reclaimed this run, so this worker must stop."""


class _EvaluationAnswerFailure(RuntimeError):
    def __init__(self, error: Exception, attempts: int):
        self.attempts = attempts
        self.retryable = bool(getattr(error, "retryable", False))
        self.cause_type = getattr(error, "cause_type", None) or type(error).__name__
        self.status_code = getattr(error, "status_code", None)
        self.diagnostic = getattr(error, "diagnostic", None)
        super().__init__("Evaluation answer generation failed.")


@broker.task
async def process_evaluation(evaluation_run_id: str) -> None:
    configure_worker_logging()
    logger.info(
        "event=worker_task_received task=evaluation run_id=%s",
        evaluation_run_id,
    )
    try:
        run_id = UUID(evaluation_run_id)
    except ValueError:
        logger.error(
            "event=worker_task_rejected task=evaluation reason=invalid_run_id run_id=%s",
            evaluation_run_id,
        )
        return

    job_started = perf_counter()
    lease_token = uuid4()
    async with SessionLocal() as session:
        run = await session.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.id == run_id)
            .with_for_update()
        )
        now = datetime.now(UTC)
        can_reclaim_stale_run = bool(
            run is not None
            and run.status == "running"
            and (
                run.worker_lease_expires_at is None
                or run.worker_lease_expires_at <= now
            )
        )
        if run is None or (run.status != "queued" and not can_reclaim_stale_run):
            logger.info(
                "event=worker_task_skipped task=evaluation run_id=%s reason=not_queued_or_expired",
                run_id,
            )
            return
        if can_reclaim_stale_run:
            logger.warning(
                "event=worker_stale_task_reclaimed task=evaluation run_id=%s previous_lease_expires_at=%s",
                run_id,
                run.worker_lease_expires_at,
            )
        expected_hashes = {
            "case": case_set_hash(),
            "answer": hashlib.sha256(ANSWER_INSTRUCTIONS.encode()).hexdigest(),
            "extraction": hashlib.sha256(
                FACT_EXTRACTION_INSTRUCTIONS.encode()
            ).hexdigest(),
        }
        if (
            run.case_set_hash != expected_hashes["case"]
            or run.answer_prompt_hash != expected_hashes["answer"]
            or run.extraction_prompt_hash != expected_hashes["extraction"]
        ):
            run.status = "failed"
            run.current_stage = "Failed"
            run.completed_at = now
            run.error_message = (
                "The evaluation case or prompt version changed before the run started. "
                "Start a new run to score the current configuration."
            )
            await session.commit()
            logger.error(
                "event=worker_task_finished task=evaluation status=failed run_id=%s reason=version_hash_mismatch",
                run_id,
            )
            return
        run.status = "running"
        run.current_stage = "Checking source files"
        run.worker_lease_token = lease_token
        run.worker_lease_expires_at = now + timedelta(
            seconds=_WORKER_LEASE_SECONDS
        )
        run.heartbeat_at = now
        run.started_at = run.started_at or now
        run.model_name = answer_model_name()
        run.error_message = None
        case_count = run.case_count
        model_name = run.model_name
        await session.commit()
    logger.info(
        "event=worker_task_claimed task=evaluation run_id=%s cases=%s answer_model=%s",
        run_id,
        case_count,
        model_name,
    )

    heartbeat_task = asyncio.create_task(
        _heartbeat_evaluation(run_id, lease_token),
        name=f"evaluation-heartbeat-{run_id}",
    )
    try:
        async with SessionLocal() as session:
            run = await session.get(EvaluationRun, run_id)
            if run is None:
                return
            snapshot = dict(run.document_snapshot or {})
            extraction_results = dict(run.extraction_results or {})
            extraction_prompt_hash = run.extraction_prompt_hash
            user_id = run.user_id
            prior_results = {
                result.get("case_id")
                for result in (run.case_results or [])
                if result.get("status") in {"evaluated", "blocked", "error"}
            }

        source_documents, source_errors = await _prepare_source_documents(
            run_id,
            lease_token,
            user_id,
            snapshot,
            extraction_results,
            extraction_prompt_hash,
        )

        for case in EVALUATION_CASES:
            if case["id"] in prior_results:
                continue
            stage = (
                f"Scoring financial-year summary {case['id']}"
                if case.get("runner") == "financial_year_summary"
                else f"Answering and scoring {case['id']}"
            )
            if not await _set_stage(run_id, lease_token, stage):
                logger.warning(
                    "event=worker_task_stopped task=evaluation run_id=%s case_id=%s reason=lease_lost_before_case",
                    run_id,
                    case["id"],
                )
                return
            if case.get("runner") == "financial_year_summary":
                result = await _evaluate_financial_year_case(
                    case,
                    snapshot,
                    source_documents,
                    source_errors,
                    user_id,
                    run_id,
                )
            else:
                result = await _evaluate_case(
                    case,
                    snapshot,
                    source_documents,
                    source_errors,
                    run_id,
                )
            if not await _save_case_result(run_id, lease_token, result):
                logger.warning(
                    "event=worker_task_stopped task=evaluation run_id=%s case_id=%s reason=lease_lost_before_result_save",
                    run_id,
                    case["id"],
                )
                return
            logger.info(
                "event=evaluation_case_finished run_id=%s case_id=%s status=%s passed=%s duration_ms=%s checks=%s",
                run_id,
                case["id"],
                result.get("status"),
                result.get("passed"),
                result.get("duration_ms"),
                result.get("checks"),
            )

        async with SessionLocal() as session:
            run = await session.scalar(
                select(EvaluationRun)
                .where(
                    EvaluationRun.id == run_id,
                    EvaluationRun.status == "running",
                    EvaluationRun.worker_lease_token == lease_token,
                )
                .with_for_update()
            )
            if run is None:
                logger.warning(
                    "event=worker_task_stopped task=evaluation run_id=%s reason=lease_lost_before_completion",
                    run_id,
                )
                return
            now = datetime.now(UTC)
            run.status = "completed"
            run.current_stage = "Completed"
            run.completed_at = now
            run.worker_lease_token = None
            run.worker_lease_expires_at = None
            run.heartbeat_at = now
            results = list(run.case_results or [])
            evaluated_count = sum(item.get("status") == "evaluated" for item in results)
            passed_count = sum(item.get("passed") is True for item in results)
            blocked_count = sum(item.get("status") == "blocked" for item in results)
            error_count = sum(item.get("status") == "error" for item in results)
            await session.commit()
        logger.info(
            "event=worker_task_finished task=evaluation status=completed run_id=%s duration_ms=%s cases=%s evaluated=%s passed=%s blocked=%s errors=%s",
            run_id,
            int((perf_counter() - job_started) * 1000),
            case_count,
            evaluated_count,
            passed_count,
            blocked_count,
            error_count,
        )
    except _EvaluationLeaseLost:
        logger.warning(
            "event=worker_task_stopped task=evaluation run_id=%s reason=lease_lost",
            run_id,
        )
        return
    except Exception as error:
        logger.exception(
            "event=worker_task_failed task=evaluation run_id=%s error_type=%s",
            run_id,
            type(error).__name__,
        )
        async with SessionLocal() as session:
            run = await session.scalar(
                select(EvaluationRun)
                .where(
                    EvaluationRun.id == run_id,
                    EvaluationRun.status == "running",
                    EvaluationRun.worker_lease_token == lease_token,
                )
                .with_for_update()
            )
            if run is not None:
                run.status = "failed"
                run.current_stage = "Failed"
                run.completed_at = datetime.now(UTC)
                run.error_message = (
                    "The evaluation runner stopped unexpectedly. Start a new run to retry."
                )
                run.worker_lease_token = None
                run.worker_lease_expires_at = None
                await session.commit()
                logger.error(
                    "event=worker_task_finished task=evaluation status=failed run_id=%s duration_ms=%s error_type=%s",
                    run_id,
                    int((perf_counter() - job_started) * 1000),
                    type(error).__name__,
                )
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Evaluation heartbeat stopped for run %s", run_id)


async def _prepare_source_documents(
    run_id: UUID,
    lease_token: UUID,
    user_id: int,
    snapshot: dict,
    extraction_results: dict,
    extraction_prompt_hash: str,
) -> tuple[dict[str, AnswerDocument], dict[str, dict[str, str]]]:
    filenames = list(
        dict.fromkeys(
            filename
            for case in EVALUATION_CASES
            for filename in case["required_documents"]
        )
    )
    documents: dict[str, AnswerDocument] = {}
    errors: dict[str, dict[str, str]] = {}

    for filename in filenames:
        source = snapshot.get(filename) or {}
        document_id_text = source.get("document_id")
        public_id = source.get("cloudinary_public_id")
        expected_hash = source.get("file_hash")
        if not document_id_text or not public_id or not expected_hash or not source.get("upload_complete"):
            errors[filename] = {
                "status": "blocked",
                "message": f"Upload {filename} completely before running this case.",
            }
            logger.warning(
                "event=evaluation_source_blocked run_id=%s filename=%r reason=missing_or_incomplete_upload",
                run_id,
                filename,
            )
            continue
        try:
            document_id = UUID(document_id_text)
        except (ValueError, TypeError):
            errors[filename] = {
                "status": "blocked",
                "message": f"The saved source reference for {filename} is invalid.",
            }
            continue

        async with SessionLocal() as session:
            document = await session.scalar(
                select(Document).where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                    func.lower(Document.filename) == filename.casefold(),
                    Document.file_hash == expected_hash,
                    Document.cloudinary_public_id == public_id,
                    Document.cloudinary_url.is_not(None),
                )
            )
        if document is None:
            errors[filename] = {
                "status": "blocked",
                "message": f"The pinned source file {filename} is no longer available.",
            }
            logger.warning(
                "event=evaluation_source_blocked run_id=%s filename=%r reason=pinned_file_unavailable",
                run_id,
                filename,
            )
            continue

        cached = extraction_results.get(filename) or {}
        if cached.get("status") == "succeeded" and cached.get("file_hash") == expected_hash:
            try:
                extracted = Extraction.model_validate(cached["content"])
                documents[filename] = _answer_document(
                    document_id,
                    document.filename,
                    extracted,
                )
                logger.info(
                    "event=evaluation_extraction_restored run_id=%s document_id=%s filename=%r model=%s facts=%s",
                    run_id,
                    document_id,
                    document.filename,
                    extracted.model,
                    len(extracted.facts),
                )
                continue
            except Exception as error:
                logger.warning(
                    "Cached evaluation extraction for %s was invalid (%s)",
                    filename,
                    type(error).__name__,
                )

        if not await _set_stage(run_id, lease_token, f"Extracting {filename}"):
            raise _EvaluationLeaseLost
        attempts = 0
        extracted = None
        failure: Exception | None = None
        for attempts in range(1, MAX_EXTRACTION_ATTEMPTS + 1):
            try:
                stage_started = perf_counter()
                logger.info(
                    "Fetching from Cloudinary | event=stage_started task=evaluation stage=cloudinary_download run_id=%s document_id=%s filename=%r attempt=%s",
                    run_id,
                    document_id,
                    filename,
                    attempts,
                )
                try:
                    content = await download_document(
                        public_id,
                        filename,
                        expected_hash,
                    )
                except Exception as error:
                    logger.error(
                        "Cloudinary fetch failed | event=stage_failed task=evaluation stage=cloudinary_download run_id=%s document_id=%s filename=%r attempt=%s duration_ms=%s error_type=%s",
                        run_id,
                        document_id,
                        filename,
                        attempts,
                        int((perf_counter() - stage_started) * 1000),
                        type(error).__name__,
                    )
                    raise
                logger.info(
                    "Fetched from Cloudinary | event=stage_finished task=evaluation stage=cloudinary_download run_id=%s document_id=%s filename=%r attempt=%s duration_ms=%s bytes=%s",
                    run_id,
                    document_id,
                    filename,
                    attempts,
                    int((perf_counter() - stage_started) * 1000),
                    len(content),
                )

                stage_started = perf_counter()
                logger.info(
                    "Sending document to Gemini for fact extraction | event=stage_started task=evaluation stage=llm_extraction run_id=%s document_id=%s filename=%r attempt=%s bytes=%s",
                    run_id,
                    document_id,
                    filename,
                    attempts,
                    len(content),
                )
                try:
                    async def report_chunk_progress(
                        chunks_completed: int,
                        chunks_total: int,
                    ) -> None:
                        if not await _set_stage(
                            run_id,
                            lease_token,
                            f"Extracting {chunks_completed} of {chunks_total} chunks",
                        ):
                            raise _EvaluationLeaseLost

                    extracted = await extract_document(
                        filename,
                        content,
                        trace_context={
                            "document_id": str(document_id),
                            "evaluation_run_id": str(run_id),
                            "source": "source-backed-evaluation",
                        },
                        on_chunk_progress=report_chunk_progress,
                    )
                except Exception as error:
                    logger.error(
                        "Gemini fact extraction failed | event=stage_failed task=evaluation stage=llm_extraction run_id=%s document_id=%s filename=%r attempt=%s duration_ms=%s error_type=%s",
                        run_id,
                        document_id,
                        filename,
                        attempts,
                        int((perf_counter() - stage_started) * 1000),
                        type(error).__name__,
                    )
                    raise
                logger.info(
                    "Received extraction from Gemini | event=stage_finished task=evaluation stage=llm_extraction run_id=%s document_id=%s filename=%r attempt=%s duration_ms=%s model=%s pipeline=%s facts=%s verified_facts=%s segments=%s",
                    run_id,
                    document_id,
                    filename,
                    attempts,
                    int((perf_counter() - stage_started) * 1000),
                    extracted.model,
                    extracted.pipeline,
                    len(extracted.facts),
                    sum(fact.verified for fact in extracted.facts),
                    len(extracted.segments),
                )
                failure = None
                break
            except TemporaryExtractionError as error:
                failure = error
                if attempts < MAX_EXTRACTION_ATTEMPTS:
                    delay = retry_delay_seconds(attempts)
                    logger.warning(
                        "event=evaluation_extraction_retry_scheduled run_id=%s document_id=%s filename=%r attempt=%s retry_delay_seconds=%s error_type=%s",
                        run_id,
                        document_id,
                        filename,
                        attempts,
                        delay,
                        type(error).__name__,
                    )
                    await asyncio.sleep(delay)
            except Exception as error:
                failure = error
                break

        if extracted is None:
            error_type = type(failure).__name__ if failure is not None else "ExtractionError"
            logger.warning(
                "event=evaluation_extraction_failed run_id=%s document_id=%s filename=%r attempts=%s error_type=%s",
                run_id,
                document_id,
                filename,
                attempts,
                error_type,
            )
            errors[filename] = {
                "status": "error",
                "message": f"Fresh extraction failed for {filename} ({error_type}).",
            }
            saved = await _save_extraction_result(
                run_id,
                lease_token,
                filename,
                {
                    "status": "error",
                    "file_hash": expected_hash,
                    "attempts": attempts,
                    "error_type": error_type,
                },
            )
            if not saved:
                raise _EvaluationLeaseLost
            continue

        extracted_payload = extracted.model_dump(mode="json")
        cache_entry = {
            "status": "succeeded",
            "file_hash": expected_hash,
            "attempts": attempts,
            "model": extracted.model,
            "pipeline": extracted.pipeline,
            "extraction_prompt_hash": extraction_prompt_hash,
            "content": extracted_payload,
        }
        if not await _save_extraction_result(
            run_id,
            lease_token,
            filename,
            cache_entry,
        ):
            raise _EvaluationLeaseLost
        logger.info(
            "event=evaluation_extraction_saved run_id=%s document_id=%s filename=%r attempts=%s model=%s facts=%s",
            run_id,
            document_id,
            filename,
            attempts,
            extracted.model,
            len(extracted.facts),
        )
        source = dict(source)
        source.update(
            {
                "extraction_model": extracted.model,
                "extraction_pipeline": extracted.pipeline,
                "extraction_prompt_hash": extraction_prompt_hash,
                "extraction_attempts": attempts,
            }
        )
        snapshot[filename] = source
        documents[filename] = _answer_document(
            document_id,
            document.filename,
            extracted,
            document.upload_timestamp,
        )

    return documents, errors


def _answer_document(
    document_id: UUID,
    filename: str,
    extracted: Extraction,
    upload_timestamp: datetime | None = None,
) -> AnswerDocument:
    return AnswerDocument(
        id=document_id,
        filename=filename,
        doc_type=extracted.doc_type,
        organisation=extracted.organisation,
        summary=extracted.summary,
        period_start=extracted.period_start,
        period_end=extracted.period_end,
        issues=extracted.issues,
        facts=[
            {
                "key": fact.key,
                "label": fact.label,
                "category": fact.category,
                "metric": fact.metric,
                "series": fact.series,
                "value_text": fact.value_text,
                "value_number": (
                    format(fact.value_number, "f")
                    if fact.value_number is not None
                    else None
                ),
                "unit": fact.unit,
                "period_start": fact.period_start,
                "period_end": fact.period_end,
                "note": fact.note,
                "origin": fact.origin,
                "locator": fact.locator.model_dump(mode="json", exclude_none=True),
                "quote": fact.quote,
                "verified": fact.verified,
                "verification": fact.verification,
                "derivation": fact.derivation,
            }
            for fact in extracted.facts
        ],
        segments=extracted.segments,
        upload_timestamp=upload_timestamp,
    )


async def _set_stage(run_id: UUID, lease_token: UUID, stage: str) -> bool:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        result = await session.execute(
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.status == "running",
                EvaluationRun.worker_lease_token == lease_token,
            )
            .values(
                current_stage=stage,
                heartbeat_at=now,
                worker_lease_expires_at=now + timedelta(seconds=_WORKER_LEASE_SECONDS),
            )
        )
        await session.commit()
        return result.rowcount == 1


async def _save_extraction_result(
    run_id: UUID,
    lease_token: UUID,
    filename: str,
    result_payload: dict,
) -> bool:
    async with SessionLocal() as session:
        run = await session.scalar(
            select(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.status == "running",
                EvaluationRun.worker_lease_token == lease_token,
            )
            .with_for_update()
        )
        if run is None:
            return False
        results = dict(run.extraction_results or {})
        results[filename] = result_payload
        run.extraction_results = results

        if result_payload.get("status") == "succeeded":
            snapshot = dict(run.document_snapshot or {})
            source = dict(snapshot.get(filename) or {})
            source.update(
                {
                    "extraction_model": result_payload.get("model"),
                    "extraction_pipeline": result_payload.get("pipeline"),
                    "extraction_prompt_hash": run.extraction_prompt_hash,
                    "extraction_attempts": result_payload.get("attempts"),
                }
            )
            snapshot[filename] = source
            run.document_snapshot = snapshot
        now = datetime.now(UTC)
        run.heartbeat_at = now
        run.worker_lease_expires_at = now + timedelta(seconds=_WORKER_LEASE_SECONDS)
        await session.commit()
        return True


async def _evaluate_case(
    case: dict,
    snapshot: dict,
    source_documents: dict[str, AnswerDocument],
    source_errors: dict[str, dict[str, str]],
    run_id: UUID,
) -> dict:
    case_result = {
        "case_id": case["id"],
        "case": public_case(case),
        "status": "blocked",
        "passed": None,
        "checks": {
            "answer": None,
            "extraction": None,
            "evidence": None,
            "calculation": None,
            "uncertainty": None,
        },
        "answer": None,
        "error_message": None,
        "failure_stage": None,
        "failure_type": None,
        "failure_attempts": None,
        "retryable": None,
        "failure_diagnostic": None,
        "answer_attempts": None,
        "document_snapshot": {},
        "duration_ms": None,
    }
    documents: list[AnswerDocument] = []
    for filename in case["required_documents"]:
        source = snapshot.get(filename) or {}
        case_result["document_snapshot"][filename] = _case_source_provenance(source)
        if filename in source_errors:
            source_error = source_errors[filename]
            case_result["status"] = source_error["status"]
            case_result["error_message"] = source_error["message"]
            return case_result
        document = source_documents.get(filename)
        if document is None:
            case_result["error_message"] = f"Upload {filename} to evaluate this case."
            return case_result
        documents.append(document)

    started = datetime.now(UTC)
    try:
        extraction_diagnostics = score_extraction_diagnostics(case, documents)
        extraction_pass = not extraction_diagnostics
        answer, status, answer_attempts = await _generate_evaluation_answer(
            case,
            documents,
            run_id,
        )
        case_result["answer_attempts"] = answer_attempts
    except _EvaluationAnswerFailure as failure:
        logger.warning(
            "event=evaluation_answer_failed run_id=%s case_id=%s stage=llm_answer error_type=%s attempts=%s retryable=%s status_code=%s diagnostic=%s",
            run_id,
            case["id"],
            failure.cause_type,
            failure.attempts,
            failure.retryable,
            failure.status_code,
            failure.diagnostic,
        )
        case_result["status"] = "error"
        case_result["error_message"] = (
            f"Answer generation failed after {failure.attempts} attempt(s) "
            f"({failure.cause_type}). See worker logs for this run and case."
        )
        case_result["failure_stage"] = "llm_answer"
        case_result["failure_type"] = failure.cause_type
        case_result["failure_attempts"] = failure.attempts
        case_result["retryable"] = failure.retryable
        case_result["failure_diagnostic"] = failure.diagnostic
        case_result["duration_ms"] = int(
            (datetime.now(UTC) - started).total_seconds() * 1000
        )
        return case_result
    except Exception as error:
        logger.warning(
            "event=evaluation_case_failed run_id=%s case_id=%s stage=case_evaluation error_type=%s",
            run_id,
            case["id"],
            type(error).__name__,
        )
        case_result["status"] = "error"
        case_result["error_message"] = (
            f"Case evaluation failed ({type(error).__name__}). "
            "See worker logs for this run and case."
        )
        case_result["failure_stage"] = "case_evaluation"
        case_result["failure_type"] = type(error).__name__
        case_result["failure_attempts"] = 0
        case_result["retryable"] = False
        case_result["duration_ms"] = int(
            (datetime.now(UTC) - started).total_seconds() * 1000
        )
        return case_result

    scored = score_case(
        case,
        answer,
        status,
        extraction_pass,
        extraction_diagnostics,
    )
    case_result.update(scored)
    case_result["status"] = "evaluated"
    case_result["answer"] = answer.model_dump(mode="json")
    case_result["duration_ms"] = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return case_result


async def _generate_evaluation_answer(
    case: dict,
    documents: list[AnswerDocument],
    run_id: UUID,
) -> tuple[AnswerContent, str, int]:
    total_started = perf_counter()
    for attempt in range(1, _MAX_ANSWER_ATTEMPTS + 1):
        attempt_started = perf_counter()
        logger.info(
            "Sending evaluation question to Gemini for an answer | event=stage_started task=evaluation stage=llm_answer run_id=%s case_id=%s source_files=%s model=%s attempt=%s/%s",
            run_id,
            case["id"],
            [document.filename for document in documents],
            answer_model_name(),
            attempt,
            _MAX_ANSWER_ATTEMPTS,
        )
        try:
            answer, status = await generate_answer_for_documents(
                case["question"],
                documents,
                trace_context={
                    "origin": "evaluation",
                    "evaluation_run_id": str(run_id),
                    "case_id": str(case["id"]),
                },
            )
        except Exception as error:
            retryable = bool(getattr(error, "retryable", False))
            cause_type = getattr(error, "cause_type", None) or type(error).__name__
            status_code = getattr(error, "status_code", None)
            diagnostic = getattr(error, "diagnostic", None)
            duration_ms = int((perf_counter() - attempt_started) * 1000)
            logger.warning(
                "Gemini evaluation answer failed | event=stage_failed task=evaluation stage=llm_answer run_id=%s case_id=%s attempt=%s/%s duration_ms=%s error_type=%s retryable=%s status_code=%s diagnostic=%s",
                run_id,
                case["id"],
                attempt,
                _MAX_ANSWER_ATTEMPTS,
                duration_ms,
                cause_type,
                retryable,
                status_code,
                diagnostic,
            )
            if retryable and attempt < _MAX_ANSWER_ATTEMPTS:
                delay = retry_delay_seconds(attempt)
                logger.info(
                    "Scheduling evaluation answer retry | event=worker_retry_scheduled task=evaluation stage=llm_answer run_id=%s case_id=%s failed_attempt=%s next_attempt=%s delay_seconds=%s error_type=%s",
                    run_id,
                    case["id"],
                    attempt,
                    attempt + 1,
                    delay,
                    cause_type,
                )
                await asyncio.sleep(delay)
                continue
            logger.error(
                "Evaluation answer attempts exhausted | event=stage_finished task=evaluation stage=llm_answer run_id=%s case_id=%s attempts=%s duration_ms=%s error_type=%s retryable=%s",
                run_id,
                case["id"],
                attempt,
                int((perf_counter() - total_started) * 1000),
                cause_type,
                retryable,
            )
            raise _EvaluationAnswerFailure(error, attempt) from error

        logger.info(
            "Received answer from Gemini | event=stage_finished task=evaluation stage=llm_answer run_id=%s case_id=%s attempt=%s duration_ms=%s status=%s evidence=%s calculations=%s model=%s",
            run_id,
            case["id"],
            attempt,
            int((perf_counter() - attempt_started) * 1000),
            status,
            len(answer.evidence),
            len(answer.calculations),
            answer.model,
        )
        return answer, status, attempt
    raise RuntimeError("Evaluation answer retry loop ended unexpectedly.")


def _case_source_provenance(source: dict) -> dict:
    return {
        key: source.get(key)
        for key in (
            "document_id",
            "file_hash",
            "status_at_start",
            "extraction_model",
            "extraction_pipeline",
            "extraction_prompt_hash",
            "extraction_attempts",
            "financial_year_extraction_run_id",
        )
    }


async def _evaluate_financial_year_case(
    case: dict,
    snapshot: dict,
    source_documents: dict[str, AnswerDocument],
    source_errors: dict[str, dict[str, str]],
    user_id: int,
    run_id: UUID,
) -> dict:
    result = {
        "case_id": case["id"],
        "case": public_case(case),
        "status": "blocked",
        "passed": None,
        "checks": {
            "answer": None,
            "extraction": None,
            "evidence": None,
            "calculation": None,
            "uncertainty": None,
        },
        "answer": None,
        "financial_year_summary": None,
        "error_message": None,
        "document_snapshot": {},
        "duration_ms": None,
    }
    filename = case["required_documents"][0]
    source = snapshot.get(filename) or {}
    result["document_snapshot"][filename] = _case_source_provenance(source)
    if filename in source_errors:
        result["status"] = source_errors[filename]["status"]
        result["error_message"] = source_errors[filename]["message"]
        return result
    if filename not in source_documents:
        result["error_message"] = f"Upload {filename} to evaluate this case."
        return result

    document_id_text = source.get("document_id")
    extraction_run_id_text = source.get("financial_year_extraction_run_id")
    if not document_id_text or not extraction_run_id_text:
        result["error_message"] = (
            "This case needs a successfully processed workbook extraction pinned when the run starts."
        )
        return result
    try:
        document_id = UUID(document_id_text)
        extraction_run_id = UUID(extraction_run_id_text)
    except (ValueError, TypeError):
        result["error_message"] = "The pinned financial-year source reference is invalid."
        return result

    started = datetime.now(UTC)
    logger.info(
        "event=stage_started task=evaluation stage=financial_year_summary run_id=%s case_id=%s filename=%r pinned_extraction_run_id=%s",
        run_id,
        case["id"],
        filename,
        extraction_run_id,
    )
    try:
        async with SessionLocal() as session:
            document = await session.scalar(
                select(Document).where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                    Document.file_hash == source.get("file_hash"),
                    func.lower(Document.filename) == filename.casefold(),
                    Document.status == "success",
                )
            )
            if document is None:
                result["error_message"] = (
                    "The pinned workbook is no longer a successfully processed source."
                )
                return result
            extraction_run = await session.scalar(
                select(ExtractionRun).where(
                    ExtractionRun.id == extraction_run_id,
                    ExtractionRun.document_id == document_id,
                    ExtractionRun.status == "succeeded",
                )
            )
            if extraction_run is None:
                result["error_message"] = (
                    "The pinned financial-year extraction result is no longer available."
                )
                return result
            organisation = (document.entity_name or "").strip().casefold()
            if not organisation:
                organisation = f"__unassigned__:{document.id}"
            summary = await get_financial_year_summary(
                session,
                user_id,
                case["financial_year_expected"]["financial_year"],
                organisation,
                [document_id],
                True,
                pinned_extraction_run_ids={document_id: extraction_run_id},
            )
        extraction_diagnostics = score_extraction_diagnostics(
            case,
            [source_documents[filename]],
        )
        extraction_pass = not extraction_diagnostics
        scored = score_financial_year_summary(
            case,
            summary,
            extraction_pass,
            extraction_diagnostics,
        )
    except Exception as error:
        logger.warning(
            "Financial-year evaluation case %s failed (%s)",
            case["id"],
            type(error).__name__,
        )
        result["status"] = "error"
        result["error_message"] = "The Financial-Year Summary could not be scored."
        return result

    result.update(scored)
    result["status"] = "evaluated"
    result["financial_year_summary"] = {
        "financial_year": summary.financial_year,
        "financial_year_start": summary.financial_year_start.isoformat(),
        "financial_year_end": summary.financial_year_end.isoformat(),
        "organisation": summary.organisation,
        "coverage_status": summary.coverage_status,
        "metrics": [metric.model_dump(mode="json") for metric in summary.metrics],
        "sources": [
            source.model_dump(mode="json", exclude={"fact_id", "document_id"})
            for source in summary.sources
        ],
        "gaps": summary.gaps,
    }
    result["duration_ms"] = int((datetime.now(UTC) - started).total_seconds() * 1000)
    logger.info(
        "event=stage_finished task=evaluation stage=financial_year_summary run_id=%s case_id=%s duration_ms=%s coverage=%s metrics=%s sources=%s checks=%s",
        run_id,
        case["id"],
        result["duration_ms"],
        summary.coverage_status,
        len(summary.metrics),
        len(summary.sources),
        result["checks"],
    )
    return result


async def _save_case_result(run_id: UUID, lease_token: UUID, result: dict) -> bool:
    async with SessionLocal() as session:
        run = await session.scalar(
            select(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.status == "running",
                EvaluationRun.worker_lease_token == lease_token,
            )
            .with_for_update()
        )
        if run is None:
            return False
        results = list(run.case_results or [])
        existing_index = next(
            (
                index
                for index, item in enumerate(results)
                if item.get("case_id") == result["case_id"]
            ),
            None,
        )
        if existing_index is None:
            results.append(result)
            run.completed_count += 1
        else:
            results[existing_index] = result
        run.case_results = results
        now = datetime.now(UTC)
        run.heartbeat_at = now
        run.worker_lease_expires_at = now + timedelta(seconds=_WORKER_LEASE_SECONDS)
        await session.commit()
        return True


async def _heartbeat_evaluation(run_id: UUID, lease_token: UUID) -> None:
    while True:
        await asyncio.sleep(_HEARTBEAT_SECONDS)
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            result = await session.execute(
                update(EvaluationRun)
                .where(
                    EvaluationRun.id == run_id,
                    EvaluationRun.status == "running",
                    EvaluationRun.worker_lease_token == lease_token,
                )
                .values(
                    heartbeat_at=now,
                    worker_lease_expires_at=now + timedelta(seconds=_WORKER_LEASE_SECONDS),
                )
            )
            await session.commit()
        if result.rowcount != 1:
            return
