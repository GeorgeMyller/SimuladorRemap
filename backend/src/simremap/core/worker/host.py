"""``SimWorkerHost``: hospeda as sessões de simulação fora do event loop (T232, T447).

Fontes: platform-foundation RF-11, RF-12, EC-04 a EC-07, EC-12; simulation-bus 6;
D-04 (modo ``process`` com ``spawn`` por padrão, ``thread`` só em testes), D-05 (duas
faixas de saída), D-08 (BLAS/OpenMP com 1 thread no worker).

Uso (dyno-bench)::

    host: SimWorkerHost = request.app.state.worker_host
    handle = await host.start_session(session_id, "simremap.dyno.runner:DynoSimTask",
                                      init_payload, sim_hz=1000)
    await handle.send({"type": "run.start", ...})      # 503 SIM_WORKER_BUSY se cheia
    async for envelope in handle.outputs():             # bytes JSON (críticos primeiro)
        ...
    await host.stop_session(session_id)                 # stop + join 5 s + terminate

Garantias:
- ``tick`` nunca corre na thread do event loop; ``send`` nunca bloqueia.
- Heartbeat a cada 0,5 s; sem heartbeat por 2 s (ou processo morto, exceção no
  ``SimTask``, backlog crítico estourado) ⇒ a sessão falha: o host injeta um único
  envelope ``worker.crashed`` (``code = SIM_WORKER_UNAVAILABLE``) na saída, regista
  ``worker.crashed`` e os comandos seguintes recebem 503 ``SIM_WORKER_UNAVAILABLE``.
  Nenhum restart automático.
- ``worker.overrun`` (máx. 1/s) quando ≥ 5 % dos ticks de uma janela de 1 s
  excedem ``dt``, com ``overrun_ticks`` e ``real_time_factor``.
- ``max_active_sessions`` (1, máx. 20): acima disso 409 ``SIM_CAPACITY_EXCEEDED``.
"""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing
import queue
import time
from collections import deque
from collections.abc import MutableSequence
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Final, Protocol

import orjson

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.core.worker.logbridge import reemit_worker_log
from simremap.core.worker.loop import WorkerSpec, process_main
from simremap.core.worker.protocol import (
    COMMAND_STOP,
    STATS_SIZE,
    StatsSlot,
    TaskSpec,
    WorkerConfig,
    WorkerState,
    WorkerStats,
)
from simremap.core.worker.queues import (
    CommandQueueFull,
    WorkerChannels,
    make_process_channels,
    output_type,
    submit_command,
)
from simremap.core.worker.thread_backend import ThreadBackend

if TYPE_CHECKING:
    from simremap.core.config import Settings

__all__ = ["AsyncOutputStream", "ProcessBackend", "SimWorkerHost", "WorkerHandle"]

log = get_logger("simremap.worker")

_PULL_TIMEOUT_S: Final = 0.05
_PULL_SLICE_S: Final = 0.01
_MONITOR_MAX_INTERVAL_S: Final = 0.25
_OVERRUN_LOG_MIN_INTERVAL_S: Final = 1.0


class WorkerBackend(Protocol):
    @property
    def mode(self) -> str: ...
    @property
    def channels(self) -> WorkerChannels: ...
    @property
    def stats(self) -> MutableSequence[float]: ...

    def start(self) -> None: ...
    def request_stop(self) -> None: ...
    def is_alive(self) -> bool: ...
    def join(self, timeout: float) -> bool: ...
    def terminate(self) -> None: ...
    def close(self) -> None: ...


class ProcessBackend:
    """Uma sessão num processo filho dedicado (``multiprocessing`` ``spawn``)."""

    def __init__(
        self,
        session_id: str,
        task_spec: TaskSpec,
        init_payload: bytes,
        sim_hz: int,
        config: WorkerConfig,
    ) -> None:
        if not isinstance(task_spec, str):
            raise TypeError("o modo process exige a tarefa como 'modulo:Classe' (importável)")
        ctx: Any = multiprocessing.get_context(config.start_method)
        self.channels: WorkerChannels = make_process_channels(ctx, config)
        self.stats: MutableSequence[float] = ctx.RawArray("d", STATS_SIZE)
        self._stop = ctx.Event()
        self._proc = ctx.Process(
            target=process_main,
            args=(
                WorkerSpec(task_spec, init_payload, sim_hz),
                self.channels,
                self.stats,
                self._stop,
                config.model_dump_json(),
            ),
            name=f"simworker-{session_id}",
            daemon=True,
        )

    @property
    def mode(self) -> str:
        return "process"

    @property
    def pid(self) -> int | None:
        pid: int | None = self._proc.pid
        return pid

    @property
    def exitcode(self) -> int | None:
        code: int | None = self._proc.exitcode
        return code

    def start(self) -> None:
        self._proc.start()

    def request_stop(self) -> None:
        self._stop.set()

    def is_alive(self) -> bool:
        return self._proc.pid is not None and self._proc.is_alive()

    def join(self, timeout: float) -> bool:
        if self._proc.pid is None:  # nunca arrancou
            return True
        self._proc.join(timeout)
        return not self._proc.is_alive()

    def terminate(self) -> None:
        if self._proc.pid is None:
            return
        self._proc.terminate()
        self._proc.join(1.0)
        if self._proc.is_alive():  # pragma: no cover - SIGTERM ignorado pelo filho
            self._proc.kill()
            self._proc.join(1.0)

    def close(self) -> None:
        commands = self.channels.commands
        for method in ("cancel_join_thread", "close"):
            fn = getattr(commands, method, None)
            if callable(fn):
                fn()


def _crash_envelope(session_id: str, reason: str, t_sim_s: float) -> bytes:
    return orjson.dumps(
        {
            "v": 1,
            "type": "worker.crashed",
            "t_sim_s": t_sim_s,
            "payload": {
                "session_id": session_id,
                "code": "SIM_WORKER_UNAVAILABLE",
                "reason": reason,
            },
        }
    )


class WorkerHandle:
    """Sessão hospedada: comandos, saídas assíncronas, estatísticas e paragem."""

    def __init__(
        self,
        session_id: str,
        backend: WorkerBackend,
        config: WorkerConfig,
        sim_hz: int,
    ) -> None:
        self.session_id = session_id
        self.sim_hz = sim_hz
        self._backend = backend
        self._config = config
        self._reader = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"simworker-reader-{session_id}"
        )
        self._injected: deque[bytes] = deque()
        self._failure: str | None = None
        self._closed = False
        self._stopped = asyncio.Event()
        self._window_t = time.monotonic()
        self._window_ticks = 0.0
        self._window_overruns = 0.0
        self._last_overrun_log = 0.0

    # ------------------------------------------------------------------ estado
    @property
    def mode(self) -> str:
        return self._backend.mode

    @property
    def backend(self) -> WorkerBackend:
        return self._backend

    @property
    def failure_reason(self) -> str | None:
        return self._failure

    @property
    def failed(self) -> bool:
        return self._failure is not None

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def worker_state(self) -> WorkerState:
        return WorkerState(int(self._backend.stats[StatsSlot.STATE]))

    @property
    def state(self) -> str:
        if self._failure is not None:
            return "crashed"
        if self._closed:
            return "stopped"
        return self.worker_state.label

    @property
    def stats(self) -> WorkerStats:
        s = self._backend.stats
        return WorkerStats(
            ticks=int(s[StatsSlot.TICKS]),
            achieved_hz=max(0.0, float(s[StatsSlot.ACHIEVED_HZ])),
            overrun_ticks=int(s[StatsSlot.OVERRUN_TICKS]),
            dropped_outputs=int(s[StatsSlot.DROPPED_OUTPUTS]),
            last_heartbeat_t_wall_s=float(s[StatsSlot.LAST_HEARTBEAT]),
            log_dropped=int(s[StatsSlot.LOG_DROPPED]),
            critical_backlog=int(s[StatsSlot.CRITICAL_BACKLOG]),
            telemetry_degraded=s[StatsSlot.TELEMETRY_DEGRADED] > 0,
            t_sim_s=max(0.0, float(s[StatsSlot.T_SIM_S])),
            state=self.state,
        )

    @property
    def real_time_factor(self) -> float:
        return self.stats.achieved_hz / self.sim_hz

    def heartbeat_age_s(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return max(0.0, now - float(self._backend.stats[StatsSlot.LAST_HEARTBEAT]))

    def is_healthy(self, now: float | None = None) -> bool:
        if self._failure is not None:
            return False
        if self._closed:
            return True
        return self.heartbeat_age_s(now) <= self._config.heartbeat_timeout_s

    # ------------------------------------------------------------------ vigilância
    def check(self, now: float | None = None) -> str | None:
        """Deteta falha (exceção, overflow, processo morto, heartbeat) e devolve o motivo."""
        if self._failure is not None or self._closed:
            return self._failure
        now = time.monotonic() if now is None else now
        state = self.worker_state
        reason: str | None = None
        if state is WorkerState.CRASHED:
            reason = "task_exception"
        elif state is WorkerState.CRITICAL_OVERFLOW:
            reason = "critical_overflow"
        elif state is WorkerState.RUNNING and not self._backend.is_alive():
            reason = "worker_exited"
        elif state is WorkerState.STOPPED and not self._closed:
            reason = "worker_stopped"
        elif (
            state is WorkerState.RUNNING
            and self.heartbeat_age_s(now) > self._config.heartbeat_timeout_s
        ):
            reason = "heartbeat_timeout"
        if reason is not None:
            self._fail(reason)
        else:
            self._check_overrun(now)
        return reason

    def _fail(self, reason: str) -> None:
        self._failure = reason
        t_sim = max(0.0, float(self._backend.stats[StatsSlot.T_SIM_S]))
        self._injected.append(_crash_envelope(self.session_id, reason, t_sim))
        self._backend.request_stop()
        log.error(
            "worker.crashed",
            session_id=self.session_id,
            code="SIM_WORKER_UNAVAILABLE",
            reason=reason,
            mode=self.mode,
            t_sim_s=t_sim,
        )

    def _check_overrun(self, now: float) -> None:
        elapsed = now - self._window_t
        if elapsed < self._config.overrun_window_s:
            return
        s = self._backend.stats
        ticks = float(s[StatsSlot.TICKS])
        overruns = float(s[StatsSlot.OVERRUN_TICKS])
        d_ticks = ticks - self._window_ticks
        d_over = overruns - self._window_overruns
        self._window_t, self._window_ticks, self._window_overruns = now, ticks, overruns
        if d_ticks <= 0 or d_over / d_ticks < self._config.overrun_ratio_threshold:
            return
        if now - self._last_overrun_log < _OVERRUN_LOG_MIN_INTERVAL_S:
            return
        self._last_overrun_log = now
        log.warning(
            "worker.overrun",
            session_id=self.session_id,
            overrun_ticks=int(overruns),
            window_overrun_ticks=int(d_over),
            window_ticks=int(d_ticks),
            real_time_factor=round((d_ticks / elapsed) / self.sim_hz, 4),
        )

    # ------------------------------------------------------------------ comandos
    async def send(self, command: dict[str, object]) -> None:
        """Enfileira ``command`` sem bloquear (503 ``SIM_WORKER_BUSY`` se a fila está cheia)."""
        kind = command.get("type") if isinstance(command, dict) else None
        if not isinstance(kind, str) or kind == COMMAND_STOP:
            raise ValueError("comando deve ser dict com 'type' (str) diferente de 'stop'")
        self.check()
        if self._failure is not None or self._closed:
            raise SimRemapError(
                f"O worker da sessão {self.session_id} não está disponível.",
                code="SIM_WORKER_UNAVAILABLE",
                session_id=self.session_id,
            )
        try:
            submit_command(self._backend.channels.commands, command)
        except CommandQueueFull:
            raise SimRemapError(
                "A fila de comandos do worker está cheia; tente de novo.",
                code="SIM_WORKER_BUSY",
                headers={"Retry-After": "1"},
                session_id=self.session_id,
            ) from None

    # ------------------------------------------------------------------ saídas
    def outputs(self) -> AsyncOutputStream:
        """Iterador assíncrono das saídas (bytes JSON); termina quando a sessão acaba."""
        return AsyncOutputStream(self)

    def _has_injected(self) -> bool:
        return bool(self._injected)

    def _take_injected(self) -> bytes | None:
        return self._injected.popleft() if self._injected else None

    def _pull_now(self) -> bytes | None:
        channels = self._backend.channels
        for lane in (channels.critical, channels.data):
            with contextlib.suppress(queue.Empty, OSError, ValueError):
                item: bytes = lane.get_nowait()
                return item
        return None

    def _pull(self, timeout: float) -> bytes | None:
        """Bloqueante (thread leitora): faixa crítica primeiro, depois a de dados."""
        channels = self._backend.channels
        deadline = time.monotonic() + timeout
        while True:
            with contextlib.suppress(queue.Empty):
                item: bytes = channels.critical.get_nowait()
                return item
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            with contextlib.suppress(queue.Empty):
                item = channels.data.get(timeout=min(_PULL_SLICE_S, remaining))
                return item

    def _finished(self) -> bool:
        if self._failure is not None:
            return True
        return self._closed and not self._backend.is_alive()

    # ------------------------------------------------------------------ paragem
    async def stop(self) -> None:
        """``stop`` + join (``stop_timeout_s``, 5 s); depois termina o worker à força."""
        if self._closed:
            await self._stopped.wait()
            return
        self._closed = True
        backend = self._backend
        backend.request_stop()
        with contextlib.suppress(queue.Full, OSError, ValueError):
            backend.channels.commands.put_nowait({"type": COMMAND_STOP})
        ended = await asyncio.to_thread(backend.join, self._config.stop_timeout_s)
        if not ended:
            log.warning(
                "worker.stop_timeout",
                session_id=self.session_id,
                timeout_s=self._config.stop_timeout_s,
                mode=self.mode,
            )
            await asyncio.to_thread(backend.terminate)
        backend.close()
        self._reader.shutdown(wait=False, cancel_futures=True)
        log.info("worker.stopped", session_id=self.session_id, mode=self.mode, clean=ended)
        self._stopped.set()


class AsyncOutputStream:
    """Ponte asyncio das saídas (``run_in_executor`` na thread leitora dedicada).

    A leitura é puxada pelo consumidor: com o consumidor parado as filas enchem e o
    worker descarta frames antigos (``dropped_outputs``), nunca o contrário. Envelopes
    ``log`` são reemitidos pelo logging do processo principal e não são entregues.
    """

    def __init__(self, handle: WorkerHandle) -> None:
        self._handle = handle

    def __aiter__(self) -> AsyncOutputStream:
        return self

    async def __anext__(self) -> bytes:
        handle = self._handle
        loop = asyncio.get_running_loop()
        while True:
            injected = handle._take_injected()
            if injected is not None:
                return injected
            try:
                item = await loop.run_in_executor(handle._reader, handle._pull, _PULL_TIMEOUT_S)
            except RuntimeError:  # leitor já encerrado por stop(): drenagem não bloqueante
                item = handle._pull_now()
                if item is None:
                    raise StopAsyncIteration from None
            if item is None:
                handle.check()
                if handle._has_injected():
                    continue
                if handle._finished():
                    raise StopAsyncIteration
                continue
            if output_type(item) == "log":
                with contextlib.suppress(orjson.JSONDecodeError):
                    envelope = orjson.loads(item)
                    if isinstance(envelope, dict):
                        reemit_worker_log(envelope, handle.session_id)
                continue
            return item


class SimWorkerHost:
    """Gestor das sessões do worker (uma por processo filho no modo ``process``)."""

    def __init__(
        self,
        config: WorkerConfig | None = None,
        *,
        max_active_sessions: int = 1,
        default_sim_hz: int = 1000,
    ) -> None:
        self.config = config or WorkerConfig()
        self.max_active_sessions = max_active_sessions
        self.default_sim_hz = default_sim_hz
        self._handles: dict[str, WorkerHandle] = {}
        self._lock = asyncio.Lock()
        self._monitor: asyncio.Task[None] | None = None
        self._running = False

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> SimWorkerHost:
        overrides.setdefault("start_timeout_s", settings.worker_start_timeout_s)
        config = WorkerConfig(mode=settings.worker_mode, **overrides)
        return cls(
            config,
            max_active_sessions=settings.max_active_sessions,
            default_sim_hz=settings.sim_hz,
        )

    # ------------------------------------------------------------------ ciclo de vida
    @property
    def mode(self) -> str:
        return self.config.mode

    @property
    def running(self) -> bool:
        return self._running

    @property
    def active_sessions(self) -> int:
        return len(self._handles)

    def sessions(self) -> list[str]:
        return list(self._handles)

    async def start(self) -> None:
        """Inicia a vigilância (0 processos filhos até à primeira sessão)."""
        if self._running:
            return
        self._running = True
        interval = min(self.config.heartbeat_interval_s / 2, _MONITOR_MAX_INTERVAL_S)
        self._monitor = asyncio.create_task(self._monitor_loop(interval), name="simworker-monitor")
        log.info(
            "worker_host.started", mode=self.mode, max_active_sessions=self.max_active_sessions
        )

    async def stop(self) -> None:
        """Para todas as sessões (em paralelo) e a vigilância."""
        handles = list(self._handles.values())
        self._handles.clear()
        if handles:
            await asyncio.gather(*(h.stop() for h in handles))
        if self._monitor is not None:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
            self._monitor = None
        self._running = False
        log.info("worker_host.stopped", stopped_sessions=len(handles))

    async def _monitor_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            self.check_all()

    def check_all(self) -> None:
        now = time.monotonic()
        for handle in list(self._handles.values()):
            handle.check(now)

    # ------------------------------------------------------------------ sessões
    def _make_backend(
        self, session_id: str, task: TaskSpec, init_payload: bytes, sim_hz: int
    ) -> WorkerBackend:
        if self.config.mode == "process":
            return ProcessBackend(session_id, task, init_payload, sim_hz, self.config)
        return ThreadBackend(session_id, task, init_payload, sim_hz, self.config)

    async def start_session(
        self,
        session_id: str,
        task: TaskSpec,
        init_payload: bytes = b"",
        *,
        sim_hz: int | None = None,
    ) -> WorkerHandle:
        """Arranca o worker da sessão e espera o ``setup`` (até ``start_timeout_s``, 5 s)."""
        hz = self.default_sim_hz if sim_hz is None else sim_hz
        if not 100 <= hz <= 1000:  # noqa: PLR2004 - faixa de sim_hz da spec
            raise ValueError(f"sim_hz {hz} fora de 100–1000")
        async with self._lock:
            if session_id in self._handles:
                raise SimRemapError(
                    f"A sessão {session_id} já tem um worker ativo.",
                    code="CONFLICT",
                    session_id=session_id,
                )
            if len(self._handles) >= self.max_active_sessions:
                raise SimRemapError(
                    f"Limite de {self.max_active_sessions} sessão(ões) ativa(s) atingido.",
                    code="SIM_CAPACITY_EXCEEDED",
                    max_active_sessions=self.max_active_sessions,
                )
            backend = self._make_backend(session_id, task, init_payload, hz)
            handle = WorkerHandle(session_id, backend, self.config, hz)
            self._handles[session_id] = handle
        try:
            await asyncio.to_thread(backend.start)
            await self._wait_ready(handle)
        except BaseException:
            self._handles.pop(session_id, None)
            await handle.stop()
            raise
        log.info(
            "worker.started",
            session_id=session_id,
            mode=backend.mode,
            sim_hz=hz,
            pid=getattr(backend, "pid", None),
        )
        return handle

    async def _wait_ready(self, handle: WorkerHandle) -> None:
        backend = handle.backend
        deadline = time.monotonic() + self.config.start_timeout_s
        while True:
            state = handle.worker_state
            if state is WorkerState.RUNNING:
                return
            if state is WorkerState.SETUP_FAILED or (
                state is WorkerState.STARTING and not backend.is_alive()
            ):
                detail = self._setup_failure_detail(handle)
                log.error("worker.setup_failed", session_id=handle.session_id, detail=detail)
                raise SimRemapError(
                    f"O worker da sessão {handle.session_id} falhou no arranque.",
                    code="SIM_WORKER_UNAVAILABLE",
                    session_id=handle.session_id,
                )
            if time.monotonic() > deadline:
                log.error(
                    "worker.start_timeout",
                    session_id=handle.session_id,
                    timeout_s=self.config.start_timeout_s,
                )
                raise SimRemapError(
                    f"O worker da sessão {handle.session_id} não arrancou em "
                    f"{self.config.start_timeout_s:g} s.",
                    code="SIM_WORKER_UNAVAILABLE",
                    session_id=handle.session_id,
                )
            await asyncio.sleep(0.005)

    @staticmethod
    def _setup_failure_detail(handle: WorkerHandle) -> str:
        item = handle._pull_now()
        if item is None:
            return "processo terminou antes do setup"
        with contextlib.suppress(orjson.JSONDecodeError, AttributeError):
            payload = orjson.loads(item).get("payload", {})
            return str(payload.get("detail", ""))[:200]
        return "erro no setup"  # pragma: no cover - envelope malformado

    def find(self, session_id: str) -> WorkerHandle | None:
        return self._handles.get(session_id)

    def get(self, session_id: str) -> WorkerHandle:
        handle = self._handles.get(session_id)
        if handle is None:
            raise SimRemapError(
                f"Não há worker para a sessão {session_id}.",
                code="RESOURCE_NOT_FOUND",
                session_id=session_id,
            )
        return handle

    async def stop_session(self, session_id: str) -> None:
        handle = self._handles.pop(session_id, None)
        if handle is not None:
            await handle.stop()

    # ------------------------------------------------------------------ health
    def health(self) -> dict[str, object]:
        """Verificação ``sim_worker`` do ``/api/v1/health`` (heartbeat nos últimos 2 s)."""
        now = time.monotonic()
        for handle in list(self._handles.values()):
            handle.check(now)
        unhealthy = [sid for sid, h in self._handles.items() if not h.is_healthy(now)]
        if unhealthy:
            detail = f"sessões sem heartbeat: {', '.join(unhealthy)}"
            return {"status": "down", "detail": detail[:200]}
        count = len(self._handles)
        return {"status": "ok", "detail": f"{count} sessões ativas ({self.mode})"}
