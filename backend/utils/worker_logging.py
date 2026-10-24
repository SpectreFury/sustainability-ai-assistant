"""Ensure Taskiq child processes emit application INFO logs."""

import logging
import sys


_LOG_FORMAT = "[%(asctime)s][%(name)s][%(levelname)-7s][%(processName)s] %(message)s"


def configure_worker_logging() -> None:
    """Configure root logging in worker children, including Python 3.14 forkserver."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    stream_handlers = [
        handler
        for handler in root_logger.handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    if not stream_handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root_logger.addHandler(handler)
        stream_handlers.append(handler)

    for handler in stream_handlers:
        if handler.level > logging.INFO:
            handler.setLevel(logging.INFO)
