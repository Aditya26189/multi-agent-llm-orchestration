import hashlib
import structlog
import logging
import os


def add_hashes(logger, method_name, event_dict):
    """Add SHA-256 truncated hashes for input/output if present."""
    for field in ("prompt_sent", "output_received", "input", "output"):
        val = event_dict.get(field)
        if val and isinstance(val, str):
            event_dict[f"{field}_hash"] = hashlib.sha256(val.encode()).hexdigest()[:16]
    return event_dict


def configure_logging():
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            add_hashes,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
