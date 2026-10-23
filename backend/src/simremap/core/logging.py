"""Logging estruturado em JSON (platform-foundation RF-13, RF-20; T228).

Cada evento vira **uma linha JSON UTF-8** em stdout com os campos obrigatórios
``ts`` (ISO-8601 UTC com milissegundos), ``level``, ``logger``, ``event`` e
``request_id`` (contextvar do pedido; ``null`` fora de um pedido) e, quando
aplicável, ``session_id``, ``run_id`` e ``code``.

- Loggers ``structlog`` (``get_logger(__name__)``) e ``logging`` padrão (uvicorn,
  alembic, bibliotecas) passam pelo mesmo renderer (``ProcessorFormatter``).
- Campos de ``logging`` passados por ``extra={...}`` entram no JSON.
- Filtro de PII (zero-PII, RF-20): chaves de dados pessoais ou de rede (``ip``,
  ``client``, ``nickname``, ``email``, ``headers``, ``body``...) são removidas e
  valores com endereço IPv4/IPv6 ou e-mail são mascarados.
- Exceções: ``exc_type`` e ``stack`` (traceback) só no log, nunca na resposta HTTP.
- O access log do uvicorn (que contém o IP do cliente) fica desativado; o evento
  ``http.request`` do middleware substitui-o sem IP.

Uso::

    from simremap.core.logging import get_logger

    log = get_logger(__name__)
    log.info("worker.overrun", session_id=sid, overrun_ticks=12, real_time_factor=0.93)
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO, Any, Final

import orjson
import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from simremap.core.request_context import request_id_var

__all__ = [
    "PII_KEY_PATTERN",
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "scrub_pii",
]

PII_KEY_PATTERN: Final = re.compile(
    r"(?i)^(ip|ips|ip_addr|ip_address|client|client_ip|client_addr|client_host|remote_addr|"
    r"remote_ip|x_forwarded_for|forwarded|user_agent|headers?|cookies?|body|request_body|"
    r"nickname|author_nickname|player_nickname|email|e_mail|phone|telefone|cpf|documento|"
    r"document|address|real_name|full_name|nome)$"
)
"""Chaves removidas de todo evento (dados pessoais, cabeçalhos, corpos e IP)."""

_IPV4: Final = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6: Final = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b")
_EMAIL: Final = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_HANDLER_MARK: Final = "_simremap_json_handler"
_UVICORN_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access")
_LEVEL_ALIASES: Final = {"warn": "warning", "exception": "error", "fatal": "critical"}


def _mask(value: str) -> str:
    value = _EMAIL.sub("[email]", value)
    value = _IPV4.sub("[ip]", value)
    return _IPV6.sub("[ip]", value)


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return _mask(value)
    if isinstance(value, Mapping):
        return {
            k: _scrub_value(v)
            for k, v in value.items()
            if not (isinstance(k, str) and PII_KEY_PATTERN.fullmatch(k))
        }
    if isinstance(value, list | tuple):
        return [_scrub_value(v) for v in value]
    return value


def scrub_pii(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Processor: remove chaves de PII e mascara IP/e-mail em valores de texto."""
    for key in [k for k in event_dict if PII_KEY_PATTERN.fullmatch(k)]:
        del event_dict[key]
    for key, value in list(event_dict.items()):
        if key in ("ts", "level", "logger"):
            continue
        event_dict[key] = _scrub_value(value)
    return event_dict


def _add_request_id(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    event_dict.setdefault("request_id", request_id_var.get())
    return event_dict


def _add_timestamp(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    now = datetime.now(UTC)
    event_dict["ts"] = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return event_dict


def _add_logger_name(logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    record = event_dict.get("_record")
    if isinstance(record, logging.LogRecord):
        event_dict["logger"] = record.name
    elif "logger" not in event_dict:
        event_dict["logger"] = getattr(logger, "name", "simremap")
    return event_dict


def _normalize_level(_logger: WrappedLogger, name: str, event_dict: EventDict) -> EventDict:
    level = event_dict.get("level") or name
    level = str(level).lower()
    event_dict["level"] = _LEVEL_ALIASES.get(level, level)
    return event_dict


def _exception_fields(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    exc_info = event_dict.pop("exc_info", None)
    if not exc_info:
        return event_dict
    if exc_info is True:
        exc_info = sys.exc_info()
    elif isinstance(exc_info, BaseException):
        exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
    if isinstance(exc_info, tuple) and exc_info[0] is not None:
        event_dict["exc_type"] = exc_info[0].__name__
        event_dict["stack"] = "".join(traceback.format_exception(*exc_info))
    return event_dict


def _event_to_str(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    event = event_dict.get("event")
    event_dict["event"] = "" if event is None else str(event)
    return event_dict


def _orjson_dumps(obj: Any, **_kwargs: Any) -> str:
    return orjson.dumps(obj, default=str, option=orjson.OPT_NON_STR_KEYS).decode("utf-8")


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        _normalize_level,
        _add_logger_name,
        _add_timestamp,
    ]


class _ExtraAdder:
    """Copia os atributos ``extra={...}`` de um ``LogRecord`` padrão para o evento."""

    _RESERVED: Final = frozenset(
        logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
        | {"message", "asctime", "taskName", "color_message"}
    )

    def __call__(self, _logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
        record = event_dict.get("_record")
        if isinstance(record, logging.LogRecord):
            for key, value in record.__dict__.items():
                if key not in self._RESERVED and not key.startswith("_"):
                    event_dict.setdefault(key, value)
            if record.exc_info and "exc_info" not in event_dict:
                event_dict["exc_info"] = record.exc_info
        return event_dict


def _build_formatter() -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*_shared_processors(), _ExtraAdder()],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _exception_fields,
            _event_to_str,
            scrub_pii,
            structlog.processors.JSONRenderer(serializer=_orjson_dumps),
        ],
    )


def configure_logging(level: str = "INFO", stream: IO[str] | None = None) -> logging.Handler:
    """Configura structlog + ``logging`` para JSON em ``stream`` (padrão ``sys.stdout``).

    Idempotente: substitui o handler JSON anterior instalado por esta função e
    devolve o novo handler (útil nos testes).
    """
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(_build_formatter())
    setattr(handler, _HANDLER_MARK, True)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_MARK, False):
            root.removeHandler(existing)
    root.addHandler(handler)

    # Anexa RotatingFileHandler para gravação persistente em arquivo de log
    log_file_cand: Path | None = None
    env_file = os.environ.get("SIMREMAP_LOG_FILE")
    env_data = os.environ.get("SIMREMAP_DATA_DIR")
    if env_file:
        log_file_cand = Path(env_file).resolve()
    elif env_data:
        log_file_cand = (Path(env_data) / "logs" / "simremap.log").resolve()
    elif Path("/data/logs").exists() or Path("/data").exists():
        log_file_cand = Path("/data/logs/simremap.log").resolve()
    else:
        root_data = Path(__file__).resolve().parents[4] / "data" / "logs" / "simremap.log"
        if root_data.parent.parent.exists():
            log_file_cand = root_data.resolve()
        else:
            log_file_cand = Path("data/logs/simremap.log").resolve()

    if log_file_cand is not None:
        with contextlib.suppress(Exception):
            log_file_cand.parent.mkdir(parents=True, exist_ok=True)
            f_handler = RotatingFileHandler(
                log_file_cand, maxBytes=15 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            f_handler.setFormatter(_build_formatter())
            setattr(f_handler, _HANDLER_MARK, True)
            root.addHandler(f_handler)

    root.setLevel(level)
    logging.getLogger("simremap").setLevel(logging.NOTSET)  # herda o nível da raiz

    for name in _UVICORN_LOGGERS:
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
    # O access log do uvicorn inclui o IP do cliente (RF-20): sempre desligado.
    logging.getLogger("uvicorn.access").disabled = True
    # Bibliotecas HTTP cliente registam URLs completas (com query string) em INFO.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))
    return handler


def get_logger(name: str = "simremap", **initial: Any) -> structlog.stdlib.BoundLogger:
    """Logger structlog com nome (campo ``logger``) e contexto inicial opcional."""
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger.bind(**initial) if initial else logger


def bind_context(**values: Any) -> None:
    """Acrescenta campos (ex.: ``session_id``) a todos os eventos do contexto atual."""
    structlog.contextvars.bind_contextvars(**values)


def clear_context(*keys: str) -> None:
    """Remove campos ligados por ``bind_context`` (todos, sem argumentos)."""
    if keys:
        structlog.contextvars.unbind_contextvars(*keys)
    else:
        structlog.contextvars.clear_contextvars()
