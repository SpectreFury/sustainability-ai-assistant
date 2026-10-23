"""Model-led fact extraction with source segments and source verification."""

import hashlib
import os
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from prompts.fact_extraction import FACT_EXTRACTION_INSTRUCTIONS
from schemas.extraction import Extraction, ExtractionOut, Fact, Locator, Segment
from services.errors import TemporaryExtractionError
from services.source_verification import verify_fact_source
from services.llm_observability import (
    capture_content_enabled,
    langfuse_observation,
    update_observation,
)
from services.monthly_fact_splitting import split_monthly_column_facts
from services.parsing import ParsedDocument, parse_document
from services.pipeline import Pipeline, get_pipeline
from services.text_sanitization import sanitize_text

_PROMPT_VERSION = "benchmark-facts-v1"
_DEFAULT_MODEL = "gemini-3.5-flash-lite"
_MAX_OUTPUT_TOKENS = 32_000


async def extract_document_facts(
    filename: str,
    content: bytes,
    trace_context: dict[str, str] | None = None,
) -> Extraction:
    pipeline = get_pipeline(os.getenv("EXTRACTION_PIPELINE"))
    parsed = parse_document(
        content,
        filename,
        all_page_images=pipeline.page_images,
    )
    output = await _invoke_model(content, parsed, pipeline, trace_context)
    issues = [sanitize_text(issue) or "" for issue in output.issues]
    facts: list[Fact] = []

    for candidate in output.facts:
        locator = Locator(
            page=candidate.source.page,
            sheet=sanitize_text(candidate.source.sheet),
            cell_range=sanitize_text(candidate.source.cell_range),
        )
        quote = sanitize_text(candidate.source.quote)
        numeric_value = _decimal_value(candidate.value_number)
        verified, reason = _verify_source(
            parsed,
            pipeline,
            locator,
            quote,
            numeric_value,
        )
        period_start = _iso_date(candidate.period_start, "period_start", candidate.key, issues)
        period_end = _iso_date(candidate.period_end, "period_end", candidate.key, issues)
        facts.append(
            Fact(
                key=sanitize_text(candidate.key) or "unknown",
                label=sanitize_text(candidate.label) or "Unlabelled fact",
                category=candidate.category,
                metric=candidate.metric,
                series=sanitize_text(candidate.series),
                value_text=sanitize_text(candidate.value_text) or "",
                value_number=numeric_value,
                unit=sanitize_text(candidate.unit),
                period_start=period_start,
                period_end=period_end,
                note=sanitize_text(candidate.note),
                origin="reported",
                locator=locator,
                quote=quote,
                verified=verified,
                verification=reason,
            )
        )

    facts = split_monthly_column_facts(facts, parsed.segments)
    facts.extend(_calculated_facts(output.doc_type, facts))

    for field_name in ("period_start", "period_end"):
        value = getattr(output, field_name)
        normalized = _iso_date(value, field_name, "document", issues)
        setattr(output, field_name, normalized)

    return Extraction(
        doc_type=output.doc_type,
        title=sanitize_text(output.title) or "Untitled document",
        organisation=sanitize_text(output.organisation),
        issuer=sanitize_text(output.issuer),
        period_start=output.period_start,
        period_end=output.period_end,
        summary=sanitize_text(output.summary) or "",
        page_count=parsed.page_count,
        facts=facts,
        issues=issues,
        segments=parsed.segments,
        model=os.getenv("GEMINI_MODEL", _DEFAULT_MODEL),
        pipeline=pipeline.name,
    )


def _verify_source(
    parsed: ParsedDocument,
    pipeline: Pipeline,
    locator: Locator,
    quote: str | None,
    value: Decimal | None,
) -> tuple[bool, str]:
    if parsed.kind == "pdf":
        if locator.page is None or locator.sheet is not None or locator.cell_range is not None:
            return False, "PDF facts must cite a physical page number"
    elif locator.page is not None or not locator.sheet or not locator.cell_range:
        return False, "Spreadsheet facts must cite a sheet and cell or range"
    return verify_fact_source(
        parsed.segments,
        locator,
        quote,
        value,
        structured=pipeline.structured_evidence,
    )


def _decimal_value(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _iso_date(
    value: str | None,
    field_name: str,
    fact_key: str,
    issues: list[str],
) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        issues.append(f"{fact_key}: {field_name} was not a valid ISO date and was left unset.")
        return None


def _days(start: str | None, end: str | None) -> int | None:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _calculated_facts(doc_type: str, facts: list[Fact]) -> list[Fact]:
    """Add the benchmark's explicit per-day bill values as separate calculations."""
    if not doc_type.endswith("_bill"):
        return []
    calculated: list[Fact] = []
    for fact in facts:
        period_days = _days(fact.period_start, fact.period_end)
        if fact.category != "consumption" or fact.value_number is None or not period_days:
            continue
        per_day = (fact.value_number / Decimal(period_days)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        calculated.append(
            Fact(
                key=f"{fact.key}_per_day",
                label=f"{fact.label} per day",
                category="consumption",
                metric=fact.metric,
                series=fact.series,
                value_text=f"{per_day:,.2f} {fact.unit or ''}".strip(),
                value_number=per_day,
                unit=f"{fact.unit}/day" if fact.unit else None,
                period_start=fact.period_start,
                period_end=fact.period_end,
                origin="calculated",
                locator=fact.locator,
                quote=None,
                verified=fact.verified,
                verification="Derived from a reported value",
                derivation=(
                    f"{fact.value_number} ÷ {period_days} days "
                    f"({fact.period_start} to {fact.period_end}, inclusive)"
                ),
            )
        )
    return calculated


def _content(parsed: ParsedDocument) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": f"File: {parsed.filename} ({parsed.kind}"
            + (f", {parsed.page_count} pages)" if parsed.page_count else ")"),
        }
    ]
    for segment in parsed.segments:
        locator = segment.locator
        if locator.page is not None:
            body = segment.text or "(no text layer)"
            if segment.scanned:
                body += f"\n(scanned page: read page {locator.page} from its image below)"
            parts.append(
                {
                    "type": "text",
                    "text": f'<page number="{locator.page}">\n{body}\n</page>',
                }
            )
        else:
            parts.append(
                {
                    "type": "text",
                    "text": (
                        f'<sheet name="{locator.sheet}" range="{locator.cell_range}">\n'
                        f"{segment.text}\n</sheet>"
                    ),
                }
            )
    for page_number, image in sorted(parsed.page_images.items()):
        parts.append({"type": "text", "text": f"Image of page {page_number}:"})
        parts.append(
            {
                "type": "media",
                "mime_type": "image/png",
                "data": image,
            }
        )
    return parts


async def _invoke_model(
    content: bytes,
    parsed: ParsedDocument,
    pipeline: Pipeline,
    trace_context: dict[str, str] | None,
) -> ExtractionOut:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY to enable document extraction.")

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    model_name = os.getenv("GEMINI_MODEL", _DEFAULT_MODEL)
    page_text = "\n\n".join(segment.text for segment in parsed.segments)
    trace_metadata = {
        **(trace_context or {}),
        "document_format": parsed.kind,
        "page_count": str(parsed.page_count or 0),
        "segment_count": str(len(parsed.segments)),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "prompt_version": _PROMPT_VERSION,
        "pipeline": pipeline.name,
    }
    trace_input: dict[str, Any] = {
        "document_id": trace_metadata.get("document_id"),
        "extraction_run_id": trace_metadata.get("extraction_run_id"),
        "document_format": parsed.kind,
        "page_count": parsed.page_count,
        "segment_count": len(parsed.segments),
        "content_sha256": trace_metadata["content_sha256"],
        "prompt_version": _PROMPT_VERSION,
        "pipeline": pipeline.name,
    }
    generation_input: dict[str, Any] = {
        "document_format": parsed.kind,
        "page_count": parsed.page_count,
        "segment_count": len(parsed.segments),
        "prompt_version": _PROMPT_VERSION,
        "pipeline": pipeline.name,
        "instructions": FACT_EXTRACTION_INSTRUCTIONS,
    }
    if capture_content_enabled():
        trace_input["source_segments"] = page_text[:60_000]
        generation_input["source_segments"] = page_text[:60_000]

    with langfuse_observation(
        as_type="span",
        name="sustainability-document-extraction",
        input=trace_input,
        metadata=trace_metadata,
    ) as trace:
        with langfuse_observation(
            as_type="generation",
            name="gemini-structured-fact-extraction",
            model=model_name,
            input=generation_input,
            metadata={"provider": "google", "prompt_version": _PROMPT_VERSION},
        ) as generation:
            try:
                model = ChatGoogleGenerativeAI(
                    model=model_name,
                    google_api_key=api_key,
                    temperature=0,
                    max_output_tokens=_MAX_OUTPUT_TOKENS,
                ).with_structured_output(ExtractionOut, include_raw=True)
                raw_result = await model.ainvoke(
                    [
                        SystemMessage(content=FACT_EXTRACTION_INSTRUCTIONS),
                        HumanMessage(content=_content(parsed)),
                    ]
                )
                if isinstance(raw_result, dict) and "parsed" in raw_result:
                    parsing_error = raw_result.get("parsing_error")
                    if parsing_error is not None:
                        raise ValueError("Gemini returned an invalid structured extraction.")
                    extraction = ExtractionOut.model_validate(raw_result.get("parsed"))
                    raw_message = raw_result.get("raw")
                else:
                    extraction = ExtractionOut.model_validate(raw_result)
                    raw_message = None
                if extraction is None:
                    raise ValueError("The model returned no structured extraction.")
                usage_details = _langchain_token_usage(raw_message)
                if usage_details:
                    update_observation(generation, usage_details=usage_details)
                update_observation(
                    generation,
                    output=(
                        extraction.model_dump(mode="json")
                        if capture_content_enabled()
                        else {
                            "doc_type": extraction.doc_type,
                            "fact_count": len(extraction.facts),
                            "fact_keys": [fact.key for fact in extraction.facts],
                        }
                    ),
                )
                update_observation(
                    trace,
                    output={
                        "doc_type": extraction.doc_type,
                        "fact_count": len(extraction.facts),
                        "model": model_name,
                        "pipeline": pipeline.name,
                    },
                )
                return extraction
            except Exception as error:
                _trace_error(trace, generation, error)
                if _is_retryable_model_error(error):
                    raise TemporaryExtractionError(
                        f"Gemini temporarily failed ({type(error).__name__})."
                    ) from error
                raise


def _trace_error(trace: Any, generation: Any, error: Exception) -> None:
    attributes = {
        "level": "ERROR",
        "status_message": type(error).__name__,
    }
    update_observation(generation, **attributes)
    update_observation(trace, **attributes)


def _is_retryable_model_error(error: Exception) -> bool:
    name = type(error).__name__.casefold()
    message = str(error).casefold()
    for attribute in ("status_code", "code"):
        status_code = getattr(error, attribute, None)
        if callable(status_code):
            status_code = status_code()
        if hasattr(status_code, "value"):
            status_code = status_code.value
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            continue
        if status_code in (408, 409, 429) or status_code >= 500:
            return True
    return any(
        marker in name or marker in message
        for marker in (
            "timeout",
            "deadline",
            "connection",
            "resourceexhausted",
            "resource_exhausted",
            "resource exhausted",
            "serviceunavailable",
            "service unavailable",
            "internalservererror",
            "toomanyrequests",
            "too many requests",
            "rate limit",
            "temporarily unavailable",
        )
    )


def _langchain_token_usage(raw_message: Any) -> dict[str, int] | None:
    if raw_message is None:
        return None
    usage = getattr(raw_message, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    aliases = {
        "input": usage.get("input_tokens"),
        "output": usage.get("output_tokens"),
        "total": usage.get("total_tokens"),
    }
    return {key: int(value) for key, value in aliases.items() if value is not None} or None
