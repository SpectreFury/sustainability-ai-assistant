import hashlib
import os
from pathlib import PurePath

import httpx

from schemas.extraction import Extraction
from services.fact_extraction import ChunkProgressCallback, extract_document_facts
from services.errors import TemporaryExtractionError
from utils.cloudinary import create_signed_raw_download_url


_MAX_DOCUMENT_BYTES = int(os.getenv("EXTRACTION_MAX_BYTES", str(50 * 1024 * 1024)))


async def download_document(
    public_id: str,
    filename: str,
    expected_hash: str | None = None,
) -> bytes:
    file_format = PurePath(filename).suffix.casefold().removeprefix(".")
    if file_format not in {"pdf", "xlsx"}:
        raise ValueError("Unsupported file type. Only .xlsx and .pdf are supported.")

    # This short-lived signed API URL works for assets whose CDN delivery is ACL
    # restricted. Do not log it: it contains a temporary download signature.
    url = create_signed_raw_download_url(public_id, file_format)
    chunks: list[bytes] = []
    total_bytes = 0
    content_hash = hashlib.sha256()

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("GET", url) as response:
                if not response.is_success:
                    cloudinary_error = response.headers.get("x-cld-error")
                    detail = f": {cloudinary_error}" if cloudinary_error else ""
                    if response.status_code in {408, 425, 429} or response.status_code >= 500:
                        raise TemporaryExtractionError(
                            f"Cloudinary temporarily failed with HTTP "
                            f"{response.status_code}{detail}."
                        )
                    raise ValueError(
                        "Cloudinary download failed with HTTP "
                        f"{response.status_code}{detail}."
                    )

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        known_size = int(content_length)
                    except ValueError:
                        known_size = None
                    if known_size is not None and known_size > _MAX_DOCUMENT_BYTES:
                        raise ValueError(
                            "Document exceeds the configured extraction size limit."
                        )

                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_DOCUMENT_BYTES:
                        raise ValueError(
                            "Document exceeds the configured extraction size limit."
                        )
                    chunks.append(chunk)
                    content_hash.update(chunk)
    except httpx.HTTPError:
        raise TemporaryExtractionError(
            "Cloudinary document download request failed temporarily."
        ) from None

    if not chunks:
        raise ValueError("Downloaded document is empty.")
    if expected_hash and content_hash.hexdigest() != expected_hash:
        raise ValueError(
            "Downloaded document checksum does not match the uploaded file."
        )
    return b"".join(chunks)


async def extract_document(
    filename: str,
    content: bytes,
    trace_context: dict[str, str] | None = None,
    on_chunk_progress: ChunkProgressCallback | None = None,
) -> Extraction:
    return await extract_document_facts(
        filename,
        content,
        trace_context=trace_context,
        on_chunk_progress=on_chunk_progress,
    )
