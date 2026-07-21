import logging
import sys
import structlog
from typing import Any

_CONFIGURED = False

logger_name_prefix = "forge"


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    
    # Configurar output para console (padrão)
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(handler)
    
    # Configurar structlog para usar o logging padrão
    if _CONFIGURED:
        return
    
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True
    )
    _CONFIGURED = True


def get_logger(name: str) -> structlog.BoundLogger:
    """Obter um logger estruturado usando logging padrão."""
    return structlog.get_logger(f"{logger_name_prefix}.{name}")
