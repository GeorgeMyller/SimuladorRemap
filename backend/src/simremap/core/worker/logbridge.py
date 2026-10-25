"""Ponte de logs do worker para o processo principal (RF-13; simulation-bus 6; T446).

O worker nunca escreve logs em stdout: cada linha vira um envelope ``log`` na faixa de
dados (descartável) e o host reemite-a pelo logging JSON do processo principal com o
``session_id``. Teto de ``log_lines_per_s`` (50) linhas por segundo e por sessão; o
excedente é contado em ``log_dropped``.

Dentro de um ``SimTask``::

    from simremap.core.worker.logbridge import worker_log

    worker_log().warning("dyno.guard_rejected", reason="engine_destroyed")

Envelope: ``{"v": 1, "type": "log", "level": "warning", "event": "...", "fields": {...}}``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Final

import orjson

__all__ = [
    "LOG_LEVELS",
    "LogRateLimiter",
    "WorkerLogBridge",
    "build_log_envelope",
    "reemit_worker_log",
    "set_worker_log",
    "worker_log",
]

LOG_LEVELS: Final = ("debug", "info", "warning", "error", "critical")
_local = threading.local()


class LogRateLimiter:
    """Janela fixa de 1 s com teto de ``max_per_s`` linhas (relógio monotónico)."""

    def __init__(self, max_per_s: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._max = max_per_s
        self._clock = clock
        self._window_start = clock()
        self._count = 0

    def allow(self) -> bool:
        now = self._clock()
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._count = 0
        if self._count >= self._max:
            return False
        self._count += 1
        return True


def build_log_envelope(level: str, event: str, fields: Mapping[str, Any]) -> bytes:
    """Serializa uma linha de log do worker no envelope interno ``log``."""
    if level not in LOG_LEVELS:
        level = "info"
    return orjson.dumps(
        {"v": 1, "type": "log", "level": level, "event": event, "fields": dict(fields)},
        default=str,
    )


class WorkerLogBridge:
    """Logger do lado do worker: envia envelopes ``log`` por ``emit`` (já com teto)."""

    def __init__(self, emit: Callable[[bytes], None]) -> None:
        self._emit = emit

    def log(self, level: str, event: str, **fields: Any) -> None:
        self._emit(build_log_envelope(level, event, fields))

    def debug(self, event: str, **fields: Any) -> None:
        self.log("debug", event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self.log("info", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self.log("warning", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.log("error", event, **fields)


class _NullBridge(WorkerLogBridge):
    def __init__(self) -> None:
        super().__init__(lambda _payload: None)


_NULL: Final = _NullBridge()


def set_worker_log(bridge: WorkerLogBridge | None) -> None:
    """Define a ponte da thread atual (chamado pelo laço do worker)."""
    _local.bridge = bridge


def worker_log() -> WorkerLogBridge:
    """Ponte de logs da sessão em execução na thread atual (nula fora do worker)."""
    bridge = getattr(_local, "bridge", None)
    return bridge if isinstance(bridge, WorkerLogBridge) else _NULL


def reemit_worker_log(envelope: Mapping[str, Any], session_id: str) -> None:
    """Lado do host: reemite um envelope ``log`` pelo logging JSON com ``session_id``."""
    from simremap.core.logging import get_logger

    level = envelope.get("level")
    level_name = level if isinstance(level, str) and level in LOG_LEVELS else "info"
    raw_fields = envelope.get("fields")
    fields = dict(raw_fields) if isinstance(raw_fields, Mapping) else {}
    fields.pop("session_id", None)
    event = str(envelope.get("event") or "worker.log")
    logger = get_logger("simremap.worker")
    getattr(logger, level_name)(event, session_id=session_id, source="worker", **fields)
