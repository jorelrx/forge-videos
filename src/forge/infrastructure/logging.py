import logging
import sys
import structlog
from typing import Any

_CONFIGURED = False
_CHILD_CONFIGURED = False

logger_name_prefix = "forge"


class _StderrLoggerFactory:
    """Logger factory de structlog que escreve em `sys.stderr`.

    O stream é resolvido a cada log, não capturado em `configure`: o capture do
    pytest troca `sys.stderr` entre testes, e um objeto capturado vira
    "I/O operation on closed file" depois.
    """

    def __call__(self, *args: Any) -> structlog.PrintLogger:
        return structlog.PrintLogger(sys.stderr)


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
    # Substitui os handlers deste módulo em vez de acumulá-los: um handler preso
    # a um stream já fechado não pode sobreviver a uma reconfiguração.
    for antigo in [h for h in root_logger.handlers if getattr(h, "_forge", False)]:
        root_logger.removeHandler(antigo)
    handler._forge = True  # type: ignore[attr-defined]
    root_logger.addHandler(handler)

    # Configurar structlog para usar o logging padrão
    if _CONFIGURED:
        return

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            # colors=False é deliberado: com colors=True o structlog chama
            # colorama.init() no Windows, que REBINDA sys.stdout e sys.stderr
            # globalmente para wrappers do stream ativo naquele instante. Se o
            # primeiro configure acontece dentro de um teste com capture ativo,
            # o wrapper prende um stream que fecha logo depois e todo log
            # seguinte estoura "I/O operation on closed file". O ganho era cor
            # cosmética; o custo era um efeito global.
            structlog.dev.ConsoleRenderer(colors=False)
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True
    )
    _CONFIGURED = True


def setup_child_logging(level: str = "INFO") -> None:
    """Rotas o log estruturado para stderr no processo filho do executor.

    O stdout do filho é o canal do protocolo JSONL: uma linha de log ali é lida
    pelo pai como evento inválido e derruba a etapa inteira. Fora do filho o
    log continua no stdout (o CLI imprime o caminho do roteiro lá e os testes
    leem dali), então esta configuração é local ao processo que emite JSONL.
    """
    global _CHILD_CONFIGURED
    if _CHILD_CONFIGURED:
        return

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            # colors=False: com cores o structlog chama colorama.init() no
            # Windows, que rebinda sys.stdout/sys.stderr globalmente para o
            # stream ativo naquele instante — e o filho não tem terminal.
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=_StderrLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CHILD_CONFIGURED = True


def get_logger(name: str) -> structlog.BoundLogger:
    """Obter um logger estruturado usando logging padrão."""
    return structlog.get_logger(f"{logger_name_prefix}.{name}")
