"""Filas limitadas entre o worker e o event loop (platform-foundation RF-12; D-05; T231).

Três canais por sessão:

- **comandos** (cliente → worker, 64): nunca descarta; cheio ⇒ ``CommandQueueFull``
  (o host converte em 503 ``SIM_WORKER_BUSY``) sem bloquear o event loop.
- **faixa crítica** (worker → cliente, 64): ``run.state``, ``event.failure``, ``ack``,
  ``worker.*``... nunca descarta. Cheia ⇒ o item fica num *backlog* local do worker
  (reenviado a cada tick, na ordem) e a sessão fica ``telemetry_degraded``; se o
  backlog passar de ``max_critical_backlog`` o worker para a sessão
  (``CRITICAL_OVERFLOW`` ⇒ ``SIM_WORKER_UNAVAILABLE``).
- **faixa de dados** (worker → cliente, 256): ``telemetry.frame``, ``event.knock``,
  ``log``; cheia ⇒ descarta o item mais antigo e conta ``dropped_outputs``.

Funciona com ``queue.Queue`` (modo ``thread``) e ``multiprocessing.Queue`` (modo
``process``): só usa ``put_nowait``/``get_nowait``/``get(timeout)``. O worker nunca
bloqueia numa fila.
"""

from __future__ import annotations

import queue
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import orjson

from simremap.core.worker.protocol import DATA_OUTPUT_TYPES, WorkerConfig

__all__ = [
    "CommandQueueFull",
    "Lane",
    "OutputRouter",
    "WorkerChannels",
    "classify_output",
    "make_process_channels",
    "make_thread_channels",
    "output_type",
    "put_drop_oldest",
    "submit_command",
]

LaneName = Literal["critical", "data"]
_TYPE_HEAD: Final = re.compile(rb'"type"\s*:\s*"([^"\\]{1,64})"')
_HEAD_BYTES: Final = 256


class Lane(Protocol):
    """Interface mínima comum a ``queue.Queue`` e ``multiprocessing.Queue``."""

    def put_nowait(self, item: Any, /) -> None: ...
    def get_nowait(self) -> Any: ...
    def get(self, block: bool = ..., timeout: float | None = ...) -> Any: ...


class CommandQueueFull(RuntimeError):
    """Fila de comandos cheia (64): o chamador recebe 503 ``SIM_WORKER_BUSY``."""


@dataclass(frozen=True, slots=True)
class WorkerChannels:
    """Canais de uma sessão: comandos, faixa crítica e faixa de dados."""

    commands: Lane
    critical: Lane
    data: Lane


def make_thread_channels(config: WorkerConfig) -> WorkerChannels:
    """Canais ``queue.Queue`` limitados (modo ``thread``)."""
    return WorkerChannels(
        commands=queue.Queue(maxsize=config.command_queue_size),
        critical=queue.Queue(maxsize=config.critical_queue_size),
        data=queue.Queue(maxsize=config.output_queue_size),
    )


def make_process_channels(ctx: Any, config: WorkerConfig) -> WorkerChannels:
    """Canais ``multiprocessing.Queue`` limitados do contexto ``ctx`` (modo ``process``)."""
    return WorkerChannels(
        commands=ctx.Queue(maxsize=config.command_queue_size),
        critical=ctx.Queue(maxsize=config.critical_queue_size),
        data=ctx.Queue(maxsize=config.output_queue_size),
    )


def submit_command(commands: Lane, command: dict[str, object]) -> None:
    """Enfileira um comando sem bloquear; fila cheia ⇒ ``CommandQueueFull``."""
    try:
        commands.put_nowait(command)
    except queue.Full as exc:
        raise CommandQueueFull("fila de comandos do worker cheia") from exc


def put_drop_oldest(lane: Lane, item: Any) -> bool:
    """Põe ``item`` na fila; cheia ⇒ descarta o mais antigo. Devolve ``True`` se descartou.

    Se o item mais antigo não puder ser retirado (ainda em trânsito no pipe do
    ``multiprocessing``) e a fila continuar cheia, o descartado é o próprio ``item``.
    Nunca bloqueia.
    """
    try:
        lane.put_nowait(item)
    except queue.Full:
        pass
    else:
        return False
    try:
        lane.get_nowait()
    except queue.Empty:
        pass
    try:
        lane.put_nowait(item)
    except queue.Full:
        pass
    return True


def output_type(payload: bytes) -> str | None:
    """Valor do campo ``type`` de um envelope JSON (cabeçalho primeiro, JSON completo depois)."""
    match = _TYPE_HEAD.search(payload, 0, _HEAD_BYTES)
    if match is not None:
        return match.group(1).decode("ascii", "replace")
    try:
        decoded = orjson.loads(payload)
    except orjson.JSONDecodeError:
        return None
    value = decoded.get("type") if isinstance(decoded, dict) else None
    return value if isinstance(value, str) else None


def classify_output(payload: bytes) -> LaneName:
    """Faixa de um envelope: ``data`` para os tipos descartáveis, ``critical`` para o resto."""
    return "data" if output_type(payload) in DATA_OUTPUT_TYPES else "critical"


class OutputRouter:
    """Encaminha as saídas do ``SimTask`` para as duas faixas (lado do worker).

    ``log_gate`` (opcional) decide se uma linha ``log`` passa (teto de linhas/s da
    ``logbridge``); recusada, não entra na fila.
    """

    def __init__(
        self,
        channels: WorkerChannels,
        max_critical_backlog: int,
        log_gate: Callable[[], bool] | None = None,
    ) -> None:
        self._critical = channels.critical
        self._data = channels.data
        self._max_backlog = max_critical_backlog
        self._backlog: deque[bytes] = deque()
        self._log_gate = log_gate
        self.dropped_outputs = 0
        self.log_dropped = 0
        self.telemetry_degraded = False

    @property
    def critical_backlog(self) -> int:
        return len(self._backlog)

    @property
    def overflowed(self) -> bool:
        """Backlog crítico acima do limite: o worker deve parar a sessão (D-05)."""
        return len(self._backlog) > self._max_backlog

    def set_log_gate(self, gate: Callable[[], bool]) -> None:
        self._log_gate = gate

    def route(self, payload: bytes) -> None:
        kind = output_type(payload)
        if kind in DATA_OUTPUT_TYPES:
            if kind == "log" and self._log_gate is not None and not self._log_gate():
                self.log_dropped += 1
                return
            if put_drop_oldest(self._data, payload):
                self.dropped_outputs += 1
            return
        self.route_critical(payload)

    def route_critical(self, payload: bytes) -> None:
        """Faixa crítica: nunca descarta; fila cheia ⇒ backlog local, na ordem."""
        if self._backlog:
            self._backlog.append(payload)
            self.flush_backlog()
            return
        try:
            self._critical.put_nowait(payload)
        except queue.Full:
            self._backlog.append(payload)
            self.telemetry_degraded = True

    def flush_backlog(self) -> None:
        """Reenvia o backlog crítico enquanto houver espaço (chamado a cada tick)."""
        while self._backlog:
            try:
                self._critical.put_nowait(self._backlog[0])
            except queue.Full:
                return
            self._backlog.popleft()
