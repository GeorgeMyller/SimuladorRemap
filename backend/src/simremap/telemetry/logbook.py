"""Montagem do ``DataLog`` no event loop (tel RF-13 a RF-16; EC-07, EC-14, EC-16; fluxo 6.2).

O ``TelemetrySampler`` grava as colunas no worker e envia-as pela faixa crítica (sem
descarte) em ``telemetry.log_open``/``log_block``/``log_end``; o ``TelemetryStream`` desvia
esses tipos para o ``Logbook``, que também recebe os envelopes públicos (``run.state`` e
``event.*``) já com ``seq``. No ``log_end`` (ou, sem ele, 2 s depois do ``run.state``
terminal ou no fecho da sessão) o log é fechado:

- cabeçalho com os metadados da sessão (``vehicle_id``, ``profile_id``, ``fuel_id``,
  ``seed``, ``calibration_hash`` da puxada), canais do catálogo, eventos com o índice da
  amostra do tick de origem (``round(t_sim_s · sim_hz) − start_tick``), segmentos por puxada
  e estado terminal;
- hash canónico, arquivo ``logs/{run_id}.simlog.gz`` e linha ``datalog``.

Escrita falhada (EC-07): o log fica em memória 60 s para nova tentativa pelo export.
Worker morto (EC-16): o log parcial é descartado (``LOG_NOT_FOUND``).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.telemetry.channels import ChannelCatalog, build_catalog
from simremap.telemetry.contracts import DataLogHeader, LogEvent, PullSegment
from simremap.telemetry.datalog import LogData, round_floats
from simremap.telemetry.repository import DatalogRepository
from simremap.telemetry.sampler import LOG_BLOCK, LOG_END, LOG_OPEN, decode_block

__all__ = ["MEMORY_KEEP_S", "Logbook", "PendingLog", "SessionMeta"]

log = get_logger("simremap.telemetry")

TERMINAL_STATES: Final = frozenset({"completed", "aborted", "engine_failed"})
LOG_EVENT_TYPES: Final = frozenset({"run.state", "event.knock", "event.failure", "event.limiter"})
END_GRACE_S: Final = 0.1
END_TIMEOUT_S: Final = 2.0
MEMORY_KEEP_S: Final = 60.0
MAX_EARLY_EVENTS: Final = 64


@dataclass(frozen=True, slots=True)
class SessionMeta:
    """Metadados do cabeçalho vindos da sessão do dyno-bench."""

    vehicle_id: str
    profile_id: str
    fuel_id: str
    seed: int
    calibration_hash: str


MetaResolver = Callable[[str, str], SessionMeta | None]
"""``(session_id, run_id)`` → metadados (``None`` se a sessão já não existe)."""


@dataclass(slots=True)
class PendingLog:
    run_id: str
    session_id: str
    start_tick: int
    sim_hz: int
    catalog: ChannelCatalog
    meta: SessionMeta | None
    blocks: list[tuple[int, np.ndarray, np.ndarray]] = field(default_factory=list)
    events: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    terminal_state: str | None = None
    ended: bool = False
    n_samples: int | None = None
    truncated: bool = False
    pulls: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task[None] | None = None


class Logbook:
    """``StreamListener`` do datalogger: logs em curso, finalização e logs em memória."""

    def __init__(
        self,
        repository: DatalogRepository | None,
        meta: MetaResolver,
        *,
        clock: Callable[[], float] | None = None,
        end_grace_s: float = END_GRACE_S,
        end_timeout_s: float = END_TIMEOUT_S,
    ) -> None:
        self.repository = repository
        self.meta = meta
        self.clock = clock
        self.end_grace_s = end_grace_s
        self.end_timeout_s = end_timeout_s
        self.pending: dict[str, PendingLog] = {}
        self.memory: dict[str, tuple[LogData, float]] = {}
        self.discarded: set[str] = set()
        self.last_closed: LogData | None = None  # último log fechado (diagnóstico)
        self._early: dict[str, list[tuple[float, str, dict[str, Any]]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ consulta
    def is_pending(self, run_id: str) -> bool:
        return run_id in self.pending

    def in_memory(self, run_id: str) -> LogData | None:
        item = self.memory.get(run_id)
        if item is None:
            return None
        data, expires = item
        if self._now() > expires:
            del self.memory[run_id]
            return None
        return data

    def _now(self) -> float:
        if self.clock is not None:
            return self.clock()
        return asyncio.get_running_loop().time()

    # ------------------------------------------------------------------ StreamListener
    def on_internal(self, session_id: str, envelope: dict[str, Any]) -> None:
        kind = envelope.get("type")
        payload: dict[str, Any] = envelope.get("payload") or {}
        run_id = str(payload.get("run_id", ""))
        try:
            if kind == LOG_OPEN:
                self._open(session_id, payload)
            elif kind == LOG_BLOCK:
                pending = self.pending.get(run_id)
                if pending is not None:
                    t, data = decode_block(payload, len(pending.catalog))
                    pending.blocks.append((int(payload["start_index"]), t, data))
            elif kind == LOG_END:
                pending = self.pending.get(run_id)
                if pending is not None:
                    pending.ended = True
                    pending.n_samples = int(payload["n_samples"])
                    pending.truncated = bool(payload.get("truncated", False))
                    pending.pulls = list(payload.get("pulls") or [])
                    self._schedule(pending, self.end_grace_s)
        except (KeyError, TypeError, ValueError) as exc:
            log.error(
                "datalog.block_invalid",
                session_id=session_id,
                run_id=run_id,
                detail=f"{type(exc).__name__}: {exc}"[:200],
            )

    def on_public(self, session_id: str, envelope: dict[str, Any]) -> None:
        kind = str(envelope.get("type"))
        payload: dict[str, Any] = envelope.get("payload") or {}
        if kind == "error":
            if payload.get("code") == "SIM_WORKER_UNAVAILABLE" and payload.get("fatal"):
                self._discard_session(session_id)
            return
        if kind not in LOG_EVENT_TYPES:
            return
        run_id = payload.get("run_id")
        if not run_id:
            return
        item = (float(envelope.get("t_sim_s", 0.0)), kind, payload)
        pending = self.pending.get(str(run_id))
        if pending is None:
            early = self._early.setdefault(str(run_id), [])
            if len(early) < MAX_EARLY_EVENTS:
                early.append(item)
            while len(self._early) > MAX_EARLY_EVENTS:
                self._early.pop(next(iter(self._early)))
            return
        pending.events.append(item)
        if kind == "run.state" and payload.get("state") in TERMINAL_STATES:
            pending.terminal_state = str(payload["state"])
            if not pending.ended:
                self._schedule(pending, self.end_timeout_s)

    def on_close(self, session_id: str) -> None:
        for pending in list(self.pending.values()):
            if pending.session_id == session_id and not pending.ended:
                self._schedule(pending, self.end_grace_s)

    # ------------------------------------------------------------------ ciclo
    def _open(self, session_id: str, payload: dict[str, Any]) -> None:
        run_id = str(payload["run_id"])
        catalog = build_catalog(int(payload["n_cyl"]), bool(payload["has_turbo"]))
        if list(catalog.names) != list(payload["channels"]):
            raise ValueError("canais do log diferentes do catálogo")
        pending = PendingLog(
            run_id=run_id,
            session_id=session_id,
            start_tick=int(payload["start_tick"]),
            sim_hz=int(payload["sim_hz"]),
            catalog=catalog,
            meta=self.meta(session_id, run_id),
        )
        for item in self._early.pop(run_id, []):
            pending.events.append(item)
            if item[1] == "run.state" and item[2].get("state") in TERMINAL_STATES:
                pending.terminal_state = str(item[2]["state"])
        self.discarded.discard(run_id)
        self.pending[run_id] = pending

    def _discard_session(self, session_id: str) -> None:
        for run_id, pending in list(self.pending.items()):
            if pending.session_id == session_id:
                if pending.task is not None:
                    pending.task.cancel()
                del self.pending[run_id]
                self.discarded.add(run_id)
                log.warning("datalog.discarded", run_id=run_id, reason="worker_unavailable")

    def _schedule(self, pending: PendingLog, delay_s: float) -> None:
        if pending.task is not None and not pending.task.done():
            pending.task.cancel()
        task = asyncio.get_running_loop().create_task(
            self._finalize_later(pending.run_id, delay_s), name=f"datalog-{pending.run_id}"
        )
        pending.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _finalize_later(self, run_id: str, delay_s: float) -> None:
        await asyncio.sleep(delay_s)
        await self.finalize(run_id)

    async def wait_idle(self) -> None:
        """Espera as finalizações agendadas (testes e shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for pending in list(self.pending.values()):
            if pending.task is None or pending.task.done():
                self._schedule(pending, 0.0)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.wait_idle(), 5.0)

    # ------------------------------------------------------------------ fecho
    def build(self, pending: PendingLog) -> LogData:
        """``LogData`` (cabeçalho canónico + colunas) a partir dos blocos e eventos."""
        catalog = pending.catalog
        blocks = sorted(pending.blocks, key=lambda b: b[0])
        expected = 0
        for start, t, _ in blocks:
            if start != expected:
                raise ValueError(f"bloco fora de ordem: {start} (esperado {expected})")
            expected += t.size
        n = expected
        if blocks:
            t_all = np.concatenate([b[1] for b in blocks])
            data = np.concatenate([b[2] for b in blocks], axis=0)
        else:
            t_all = np.zeros(0, dtype=np.float64)
            data = np.zeros((0, len(catalog)), dtype=np.float32)
        terminal = pending.terminal_state or "aborted"
        last = max(n - 1, 0)
        events = [
            LogEvent(
                index=min(max(round(t * pending.sim_hz) - pending.start_tick, 0), last),
                type=kind,  # type: ignore[arg-type]
                payload=round_floats(payload),
            )
            for t, kind, payload in sorted(pending.events, key=lambda e: e[0])
        ]
        meta = pending.meta
        if meta is None:
            raise ValueError("metadados da sessão indisponíveis")
        header = DataLogHeader(
            run_id=pending.run_id,
            session_id=pending.session_id,
            vehicle_id=meta.vehicle_id,
            profile_id=meta.profile_id,
            calibration_hash=meta.calibration_hash,
            fuel_id=meta.fuel_id,
            seed=meta.seed,
            sim_hz=pending.sim_hz,
            start_tick=pending.start_tick,
            n_samples=n,
            channels=list(catalog.channels),
            pulls=self._pulls(pending, events, n, terminal),
            events=events,
            terminal_state=terminal,  # type: ignore[arg-type]
            truncated=pending.truncated,
        )
        return LogData.build(header, t_all, np.ascontiguousarray(data.T))

    @staticmethod
    def _pulls(
        pending: PendingLog, events: list[LogEvent], n: int, terminal: str
    ) -> list[PullSegment]:
        if pending.pulls:
            return [
                PullSegment(
                    pull_index=int(p["pull_index"]),
                    start_index=min(int(p["start_index"]), n),
                    end_index=min(int(p["end_index"]), n),
                    state=str(p["state"]),
                )
                for p in pending.pulls
            ]
        starts: list[tuple[int, int]] = []
        for event in events:
            payload = event.payload
            if event.type != "run.state" or payload.get("phase") != "arming":
                continue
            index = int(payload.get("pull_index") or 1)
            if not starts or starts[-1][0] != index:
                starts.append((index, 0 if not starts else event.index))
        if not starts:
            starts = [(1, 0)]
        segments: list[PullSegment] = []
        for i, (pull_index, start) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else n
            state = terminal if i + 1 == len(starts) else "completed"
            segments.append(
                PullSegment(pull_index=pull_index, start_index=start, end_index=end, state=state)
            )
        return segments

    async def finalize(self, run_id: str) -> LogData | None:
        """Fecha, grava e regista o log (``None`` se descartado ou inválido)."""
        pending = self.pending.get(run_id)
        if pending is None:
            return None
        meta = self.meta(pending.session_id, run_id)
        if meta is not None:
            pending.meta = meta
        try:
            data = self.build(pending)
        except (ValueError, SimRemapError) as exc:
            self.pending.pop(run_id, None)
            self.discarded.add(run_id)
            log.error("datalog.build_failed", run_id=run_id, detail=str(exc)[:200])
            return None
        if self.repository is not None:
            try:
                await self.repository.save(data, log_id=run_id, source="simulated")
            except SimRemapError as exc:
                if exc.error_code == "STORAGE_FULL":
                    self.memory[run_id] = (data, self._now() + MEMORY_KEEP_S)
                    log.warning("datalog.kept_in_memory", run_id=run_id, code=exc.error_code)
                else:
                    log.error("datalog.save_failed", run_id=run_id, code=exc.error_code)
        self.pending.pop(run_id, None)
        self.last_closed = data
        return data

    async def retry_memory(self, run_id: str) -> LogData | None:
        """Nova escrita de um log mantido em memória (export, EC-07)."""
        data = self.in_memory(run_id)
        if data is None or self.repository is None:
            return data
        await self.repository.save(data, log_id=run_id, source="simulated")
        self.memory.pop(run_id, None)
        return data
