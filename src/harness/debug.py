"""Debug logging helpers for the harness execution lifecycle."""

from __future__ import annotations

import logging
from typing import Any

from config.logging import get_logger

logger = get_logger(__name__)


def log_event(event: object, *, phase: str) -> None:
    """Log one complete harness event when DEBUG logging is enabled."""

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "harness event phase=%s type=%s payload=%r",
            phase,
            type(event).__name__,
            event,
        )


def log_detail(message: str, *values: Any) -> None:
    """Log detailed harness state without doing work when DEBUG is disabled."""

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(message, *values)
