import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_langfuse_client():
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import get_client

        return get_client()
    except Exception as error:
        logger.warning(
            "Langfuse initialization failed; tracing is disabled (%s).",
            type(error).__name__,
        )
        return None


def capture_content_enabled() -> bool:
    return os.getenv("LANGFUSE_CAPTURE_CONTENT", "true").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


@contextmanager
def langfuse_observation(**attributes: Any) -> Iterator[Any | None]:
    """Create a Langfuse observation when configured, without blocking extraction."""
    client = get_langfuse_client()
    if client is None:
        yield None
        return

    try:
        manager = client.start_as_current_observation(**attributes)
        observation = manager.__enter__()
    except Exception as error:
        logger.warning(
            "Langfuse observation could not start (%s).",
            type(error).__name__,
        )
        yield None
        return

    try:
        yield observation
    except BaseException as error:
        try:
            manager.__exit__(type(error), error, error.__traceback__)
        except Exception as tracing_error:
            logger.warning(
                "Langfuse observation could not close (%s).",
                type(tracing_error).__name__,
            )
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as error:
            logger.warning(
                "Langfuse observation could not close (%s).",
                type(error).__name__,
            )


def update_observation(observation: Any | None, **attributes: Any) -> None:
    if observation is None:
        return
    try:
        observation.update(**attributes)
    except Exception as error:
        logger.warning(
            "Langfuse observation update failed (%s).",
            type(error).__name__,
        )
