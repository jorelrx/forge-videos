import logging

import structlog

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    if _CONFIGURED:
        return
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    _CONFIGURED = True


def get_logger(name: str):
    return structlog.get_logger(name)
