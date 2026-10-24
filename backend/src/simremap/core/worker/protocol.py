"""Contratos do worker do laço de simulação (platform-foundation seção 8; simulation-bus 3.6 e 6).

Este módulo é importado DENTRO do worker (processo ``spawn`` ou thread): só usa a
biblioteca padrão e ``pydantic``; nunca importa ``fastapi`` nem toca no banco.

- ``SimTask``: implementado por dyno-bench; corre só no worker.
- ``WorkerConfig`` / ``WorkerStats``: configuração e estatísticas do host.
- ``StatsSlot`` / ``WorkerState``: layout do bloco de estatísticas partilhado
  (``multiprocessing.RawArray('d')`` no modo ``process``, lista no modo ``thread``),
  escrito só pelo worker e lido pelo host sem bloqueio.
- ``DATA_OUTPUT_TYPES``: tipos de saída da faixa de dados (descarte do mais antigo);
  todos os outros tipos seguem pela faixa crítica, sem descarte (D-05).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from enum import IntEnum
from typing import Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "COMMAND_STOP",
    "DATA_OUTPUT_TYPES",
    "STATS_SIZE",
    "SimTask",
    "StatsSlot",
    "TaskSpec",
    "WorkerConfig",
    "WorkerState",
    "WorkerStats",
    "resolve_task",
]

COMMAND_STOP: Final = "stop"
"""Comando reservado ao host: ``teardown`` do ``SimTask`` e fim do laço."""

DATA_OUTPUT_TYPES: Final = frozenset({"telemetry.frame", "event.knock", "log"})
"""Saídas descartáveis (faixa de dados, 256). ``run.state``, ``event.failure``,
``ack``, ``run.result``, ``datalog.closed``, ``worker.*`` e tipos desconhecidos vão
para a faixa crítica (sem descarte)."""


@runtime_checkable
class SimTask(Protocol):
    """Tarefa de simulação hospedada pelo ``SimWorkerHost`` (dono: dyno-bench).

    Regras: ``tick`` avança exatamente ``dt = 1 / sim_hz``; ``t_sim_s`` vem só da
    contagem de ticks; ``drain_outputs`` devolve envelopes JSON já serializados e
    decimados (cada um com o campo ``type``).
    """

    def setup(self, init_payload: bytes) -> None: ...
    def handle_command(self, command: dict[str, object]) -> None: ...
    def tick(self) -> None: ...
    def drain_outputs(self) -> list[bytes]: ...
    def teardown(self) -> None: ...


TaskSpec = str | Callable[[], SimTask]
"""``"pacote.modulo:Classe"`` (obrigatório no modo ``process``) ou fábrica sem argumentos."""


def resolve_task(spec: TaskSpec) -> SimTask:
    """Instancia a tarefa a partir de ``"modulo:atributo"`` ou de uma fábrica."""
    if callable(spec):
        task = spec()
    else:
        module_name, sep, attr = spec.partition(":")
        if not sep or not module_name or not attr:
            raise ValueError(f"especificação de tarefa inválida: {spec!r} (use 'modulo:Classe')")
        target = importlib.import_module(module_name)
        for part in attr.split("."):
            target = getattr(target, part)
        if not callable(target):
            raise TypeError(f"{spec!r} não é chamável")
        task = target()
    if not isinstance(task, SimTask):
        raise TypeError(f"{type(task).__name__} não implementa SimTask")
    return task


class WorkerConfig(BaseModel):
    """Parâmetros do host (platform-foundation seção 8; D-04, D-05)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["process", "thread"] = "process"
    start_method: Literal["spawn", "forkserver"] = "spawn"
    command_queue_size: int = Field(64, ge=8, le=1024)
    output_queue_size: int = Field(256, ge=16, le=4096)
    critical_queue_size: int = Field(64, ge=8, le=1024)
    max_critical_backlog: int = Field(4096, ge=0, le=65536)
    heartbeat_interval_s: float = Field(0.5, gt=0, le=5)
    heartbeat_timeout_s: float = Field(2.0, gt=0, le=30)
    stop_timeout_s: float = Field(5.0, gt=0, le=30)
    start_timeout_s: float = Field(20.0, gt=0, le=60)
    log_lines_per_s: int = Field(50, ge=1, le=10_000)
    overrun_window_s: float = Field(1.0, gt=0, le=10)
    overrun_ratio_threshold: float = Field(0.05, gt=0, le=1)
    max_commands_per_tick: int = Field(16, ge=1, le=1024)


class WorkerStats(BaseModel):
    """Estatísticas de uma sessão do worker (lidas do bloco partilhado)."""

    model_config = ConfigDict(frozen=True)

    ticks: int = Field(..., ge=0)
    achieved_hz: float = Field(..., ge=0)
    overrun_ticks: int = Field(..., ge=0)
    dropped_outputs: int = Field(..., ge=0)
    last_heartbeat_t_wall_s: float
    log_dropped: int = Field(0, ge=0)
    critical_backlog: int = Field(0, ge=0)
    telemetry_degraded: bool = False
    t_sim_s: float = Field(0.0, ge=0)
    state: str = "starting"


class StatsSlot(IntEnum):
    """Índices do bloco de estatísticas partilhado (``float64``)."""

    STATE = 0
    TICKS = 1
    ACHIEVED_HZ = 2
    OVERRUN_TICKS = 3
    DROPPED_OUTPUTS = 4
    LAST_HEARTBEAT = 5
    LOG_DROPPED = 6
    CRITICAL_BACKLOG = 7
    TELEMETRY_DEGRADED = 8
    T_SIM_S = 9


STATS_SIZE: Final = len(StatsSlot)


class WorkerState(IntEnum):
    """Estado do worker gravado em ``StatsSlot.STATE``."""

    STARTING = 0
    RUNNING = 1
    STOPPED = 2
    SETUP_FAILED = 3
    CRASHED = 4
    CRITICAL_OVERFLOW = 5

    @property
    def label(self) -> str:
        return self.name.lower()
