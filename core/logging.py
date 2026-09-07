import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    return _trace_id_var.get()


def set_trace_id(trace_id: str | None = None) -> str:
    tid = trace_id or str(uuid.uuid4())
    _trace_id_var.set(tid)
    return tid


def _add_trace_id(
    logger: logging.Logger, method_name: str, event_dict: dict
) -> dict:
    event_dict["trace_id"] = get_trace_id()
    return event_dict


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_trace_id,
    ]

    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
