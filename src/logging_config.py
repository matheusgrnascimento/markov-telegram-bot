"""Configuração centralizada dos logs estruturados do bot."""

import logging
import sys

import structlog


def reorder_event_dict(_, __, event_dict):
    """
    Garante ordem:
    level, timestamp, logger, event, resto
    """
    ordered = {}

    for key in ("level", "timestamp", "logger", "event"):
        if key in event_dict:
            ordered[key] = event_dict.pop(key)

    ordered.update(event_dict)

    return ordered


def configure_logging() -> None:
    """Configura logs JSON para a aplicação e bibliotecas que usam stdlib."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        reorder_event_dict,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
