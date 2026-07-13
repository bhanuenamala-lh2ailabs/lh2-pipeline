"""Structured logging setup. Falls back to stdlib if structlog is absent."""

from __future__ import annotations

import logging
from typing import Any

try:
    import structlog

    _HAVE_STRUCTLOG = True
except Exception:  # pragma: no cover
    _HAVE_STRUCTLOG = False


def configure(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    if _HAVE_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, level, logging.INFO)
            ),
        )


def get_logger(name: str = "lh2") -> Any:
    if _HAVE_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name)
