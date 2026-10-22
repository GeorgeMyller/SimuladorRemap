"""Laço de tempo real do worker (executado só no processo filho ou na thread do worker).

Regras de isolamento (simulation-bus 6): este módulo nunca importa ``fastapi`` nem
toca no banco; o event loop asyncio nunca chama ``SimTask.tick``.

Ritmo: o laço cadencia ``tick()`` a ``sim_hz`` por *deadlines* de parede
(``time.perf_counter``), que só servem para o tempo real e para contar
``overrun_ticks`` (tick com custo de parede > ``dt · wall_budget_ticks``); ``t_sim_s`` é sempre
``tick_index / sim_hz``. Atraso acumulado acima de 50 ms é abandonado (sem rajadas
de recuperação); a física continua determinística.

Orçamento de parede: um ``SimTask`` pode expor ``wall_budget_ticks`` (int ≥ 1, opcional,
lido depois de cada ``tick``) quando o tick avança vários passos simulados de propósito
(ex.: arrefecimento acelerado da ``multi_pull``, 10 passos por tick). Só o limiar do
diagnóstico muda; a cadência e a física continuam iguais (T031).

Heartbeat: ``StatsSlot.LAST_HEARTBEAT`` recebe ``time.monotonic()`` a cada
``heartbeat_interval_s`` (0,5 s); o host marca a sessão como falhada sem heartbeat
por ``heartbeat_timeout_s`` (2 s).
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import MutableSequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

import orjson

from simremap.core.worker.logbridge import LogRateLimiter, WorkerLogBridge, set_worker_log
from simremap.core.worker.protocol import (
    COMMAND_STOP,
    SimTask,
    StatsSlot,
    TaskSpec,
    WorkerConfig,
    WorkerState,
    resolve_task,
)
from simremap.core.worker.queues import OutputRouter, WorkerChannels

__all__ = ["BLAS_ENV_VARS", "StopSignal", "WorkerSpec", "process_main", "run_worker"]

BLAS_ENV_VARS: Final = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
)
_MAX_LAG_S: Final = 0.05
_SLEEP_MIN_S: Final = 0.0002


class StopSignal(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    """O que o worker executa: tarefa, ``init_payload`` e ``sim_hz`` (picklable no modo process)."""

    task_spec: TaskSpec
    init_payload: bytes
    sim_hz: int


def _envelope(kind: str, t_sim_s: float, **payload: Any) -> bytes:
    return orjson.dumps({"v": 1, "type": kind, "t_sim_s": t_sim_s, "payload": payload}, default=str)


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]


def _wall_budget_ticks(task: SimTask) -> int:
    """Ticks de parede que o último ``tick`` pode gastar sem contar overrun (padrão 1)."""
    budget = getattr(task, "wall_budget_ticks", 1)
    return budget if isinstance(budget, int) and budget > 1 else 1


class _Loop:
    """Estado do laço de uma sessão (instância única por worker)."""

    def __init__(
        self,
        spec: WorkerSpec,
        channels: WorkerChannels,
        stats: MutableSequence[float],
        stop: StopSignal,
        config: WorkerConfig,
    ) -> None:
        self.task_spec = spec.task_spec
        self.init_payload = spec.init_payload
        self.sim_hz = spec.sim_hz
        self.dt = 1.0 / spec.sim_hz
        self.channels = channels
        self.stats = stats
        self.stop = stop
        self.config = config
        limiter = LogRateLimiter(config.log_lines_per_s)
        self.router = OutputRouter(channels, config.max_critical_backlog, limiter.allow)
        self.log = WorkerLogBridge(self.router.route)
        self.task: SimTask | None = None
        self.tick_index = 0
        self.overrun_ticks = 0

    # ------------------------------------------------------------------ estatísticas
    def _t_sim(self) -> float:
        return self.tick_index / self.sim_hz

    def _publish(self) -> None:
        s = self.stats
        s[StatsSlot.TICKS] = float(self.tick_index)
        s[StatsSlot.T_SIM_S] = self._t_sim()
        s[StatsSlot.OVERRUN_TICKS] = float(self.overrun_ticks)
        s[StatsSlot.DROPPED_OUTPUTS] = float(self.router.dropped_outputs)
        s[StatsSlot.LOG_DROPPED] = float(self.router.log_dropped)
        s[StatsSlot.CRITICAL_BACKLOG] = float(self.router.critical_backlog)
        s[StatsSlot.TELEMETRY_DEGRADED] = 1.0 if self.router.telemetry_degraded else 0.0

    def _heartbeat(self) -> None:
        self.stats[StatsSlot.LAST_HEARTBEAT] = time.monotonic()

    def _set_state(self, state: WorkerState) -> None:
        self._publish()
        self.stats[StatsSlot.STATE] = float(state)

    def _emit_outputs(self, task: SimTask) -> None:
        for payload in task.drain_outputs():
            self.router.route(payload)

    # ------------------------------------------------------------------ ciclo de vida
    def run(self) -> None:
        set_worker_log(self.log)
        try:
            self._run()
        finally:
            set_worker_log(None)

    def _run(self) -> None:
        self._heartbeat()
        try:
            task = resolve_task(self.task_spec)
            task.setup(self.init_payload)
            self.task = task
            self._emit_outputs(task)
        except Exception as exc:
            self.router.route_critical(
                _envelope(
                    "worker.setup_failed", 0.0, code="SIM_WORKER_UNAVAILABLE", detail=_describe(exc)
                )
            )
            self._set_state(WorkerState.SETUP_FAILED)
            return
        self._heartbeat()
        self._set_state(WorkerState.RUNNING)
        final_state = self._loop(task)
        try:
            task.teardown()
            self._emit_outputs(task)
        except Exception as exc:
            self.log.error("worker.teardown_failed", detail=_describe(exc))
        self.router.flush_backlog()
        self._set_state(final_state)

    def _drain_commands(self, task: SimTask) -> bool:
        """Processa até ``max_commands_per_tick`` comandos; ``True`` ⇒ ``stop`` recebido."""
        for _ in range(self.config.max_commands_per_tick):
            try:
                command = self.channels.commands.get_nowait()
            except queue.Empty:
                return False
            if isinstance(command, dict) and command.get("type") == COMMAND_STOP:
                return True
            task.handle_command(command)
        return False

    def _loop(self, task: SimTask) -> WorkerState:
        cfg = self.config
        clock = time.perf_counter
        next_deadline = clock()
        last_heartbeat = time.monotonic()
        window_start = clock()
        window_ticks = 0
        while not self.stop.is_set():
            tick_start = clock()
            try:
                if self._drain_commands(task):
                    return WorkerState.STOPPED
                task.tick()
                self.tick_index += 1
                self._emit_outputs(task)
            except Exception as exc:
                self._crash(exc)
                return WorkerState.CRASHED
            self.router.flush_backlog()
            if self.router.overflowed:
                self.log.error("worker.critical_overflow", backlog=self.router.critical_backlog)
                return WorkerState.CRITICAL_OVERFLOW

            now = clock()
            if now - tick_start > self.dt * _wall_budget_ticks(task):
                self.overrun_ticks += 1
            window_ticks += 1
            if now - window_start >= 1.0:
                self.stats[StatsSlot.ACHIEVED_HZ] = window_ticks / (now - window_start)
                window_start = now
                window_ticks = 0
            mono = time.monotonic()
            if mono - last_heartbeat >= cfg.heartbeat_interval_s:
                last_heartbeat = mono
                self.stats[StatsSlot.LAST_HEARTBEAT] = mono
            self._publish()

            next_deadline += self.dt
            delay = next_deadline - clock()
            if delay > _SLEEP_MIN_S:
                time.sleep(delay)
            elif delay < -_MAX_LAG_S:
                next_deadline = clock()
        return WorkerState.STOPPED

    def _crash(self, exc: BaseException) -> None:
        """Exceção não tratada no ``SimTask``: regista e termina (o host emite o crash)."""
        self.log.error(
            "worker.task_exception",
            detail=_describe(exc),
            exc_type=type(exc).__name__,
            t_sim_s=self._t_sim(),
        )


def run_worker(
    spec: WorkerSpec,
    channels: WorkerChannels,
    stats: MutableSequence[float],
    stop: StopSignal,
    config: WorkerConfig,
) -> None:
    """Executa o laço de uma sessão até ``stop``, comando ``stop``, falha ou overflow."""
    _Loop(spec, channels, stats, stop, config).run()


def process_main(
    spec: WorkerSpec,
    channels: WorkerChannels,
    stats: MutableSequence[float],
    stop: StopSignal,
    config_json: str,
) -> None:
    """Ponto de entrada do processo filho (``spawn``): BLAS/OpenMP com 1 thread (D-08)."""
    for name in BLAS_ENV_VARS:
        os.environ[name] = "1"
    threading.current_thread().name = "simworker-main"
    config = WorkerConfig.model_validate_json(config_json)
    try:
        run_worker(spec, channels, stats, stop, config)
    finally:
        # A faixa de dados pode ficar cheia sem consumidor: não bloquear a saída do processo.
        cancel = getattr(channels.data, "cancel_join_thread", None)
        if callable(cancel):
            cancel()
