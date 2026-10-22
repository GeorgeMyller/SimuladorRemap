"""``TelemetryService`` (``app.state.telemetry_service``): ligação ao dyno-bench e ao banco.

``install`` usa os pontos de assinatura existentes do dyno-bench:

- ``DynoService.task_options["sampler"] = SAMPLER_SPEC``: as sessões novas usam o
  ``TelemetrySampler`` (frames com o catálogo completo e log à taxa total);
- ``app.state.dyno_stream_hub``: passa a criar ``TelemetryStream`` (desvio dos blocos de
  log para o ``Logbook``, replay de 10 s e ``seq`` local), sem trocar o objeto partilhado.

Comandos do WebSocket para o worker (pela fila de comandos, sem bloquear):
``control.throttle`` → ``operator.throttle`` e ``fps`` da subscrição → ``telemetry.config``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.dyno.contracts import TERMINAL_RUN_STATES
from simremap.dyno.stream import SessionStream
from simremap.telemetry.broadcaster import TelemetryStream, install_stream_hub
from simremap.telemetry.channels import ChannelCatalog, catalog_for_vehicle
from simremap.telemetry.datalog import LogData
from simremap.telemetry.errors import telemetry_error
from simremap.telemetry.logbook import Logbook, SessionMeta
from simremap.telemetry.repository import DatalogRepository
from simremap.telemetry.sampler import SAMPLER_SPEC

if TYPE_CHECKING:
    from simremap.dyno.session import DynoService, SessionRuntime

__all__ = ["MAX_CONNECTIONS", "TelemetryService"]

log = get_logger("simremap.telemetry")

MAX_CONNECTIONS = 4


@dataclass(slots=True)
class _SessionState:
    connections: int = 0
    fps: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    wants: dict[int, tuple[bool, bool]] = field(default_factory=dict)  # conexão → (esp., traço)
    sent: tuple[bool, bool] = (False, False)  # último telemetry.config enviado ao worker


class TelemetryService:
    """Estado do telemetry-datalogger partilhado pelo WebSocket e pelos endpoints REST."""

    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession] | None,
        data_dir: Path,
        dyno: DynoService | None = None,
        *,
        default_fps: int = 50,
    ) -> None:
        self.dyno = dyno
        self.default_fps = default_fps
        self.repository = None if maker is None else DatalogRepository(maker, data_dir)
        self.logbook = Logbook(self.repository, self._meta)
        self._sessions: dict[str, _SessionState] = {}

    # ------------------------------------------------------------------ instalação
    def install(self) -> None:
        dyno = self.dyno
        if dyno is None:
            return
        dyno.task_options.setdefault("sampler", SAMPLER_SPEC)
        # Espectro e traço desligados até alguma conexão os pedir (telemetry.config).
        dyno.task_options.setdefault("spectrum", False)
        dyno.task_options.setdefault("pressure_trace", False)
        install_stream_hub(dyno.streams, self.logbook)
        log.info("telemetry.installed", sampler=dyno.task_options.get("sampler"))

    async def shutdown(self) -> None:
        await self.logbook.shutdown()

    # ------------------------------------------------------------------ sessões
    def runtime(self, session_id: str) -> SessionRuntime | None:
        return None if self.dyno is None else self.dyno.runtime(session_id)

    def stream(self, session_id: str) -> SessionStream | None:
        if self.dyno is None:
            return None
        stream = self.dyno.streams.get(session_id)
        rt = self.dyno.runtime(session_id)
        if stream is None or rt is None or stream.closed:
            return None
        return stream

    def catalog(self, session_id: str) -> ChannelCatalog | None:
        rt = self.runtime(session_id)
        return None if rt is None else catalog_for_vehicle(rt.vehicle)

    def _state(self, session_id: str) -> _SessionState:
        return self._sessions.setdefault(session_id, _SessionState())

    def try_connect(self, session_id: str) -> bool:
        """Reserva 1 das 4 conexões da sessão (``False`` na 5.ª)."""
        state = self._state(session_id)
        if state.connections >= MAX_CONNECTIONS:
            return False
        state.connections += 1
        stream = self.stream(session_id)
        if isinstance(stream, TelemetryStream):
            stream.connections = state.connections
        return True

    def disconnect(self, session_id: str, connection_id: int | None = None) -> None:
        state = self._sessions.get(session_id)
        if state is None:
            return
        if connection_id is not None:
            state.wants.pop(connection_id, None)
        state.connections = max(0, state.connections - 1)
        if state.connections == 0:
            self._sessions.pop(session_id, None)

    def spectrum_available(self, session_id: str) -> bool:
        """O laço da sessão liga o gerador do espectro do dano ao amostrador."""
        rt = self.runtime(session_id)
        return rt is not None and bool(getattr(rt, "spectrum_available", False))

    async def set_composites(
        self, session_id: str, connection_id: int, *, spectrum: bool, pressure_trace: bool
    ) -> None:
        """Pedido de espectro/traço de uma conexão; o worker calcula-os com ≥ 1 pedido."""
        state = self._state(session_id)
        state.wants[connection_id] = (spectrum, pressure_trace)
        await self._sync_composites(session_id, state)

    async def release_composites(self, session_id: str, connection_id: int) -> None:
        """Conexão fechada: retira o pedido dela (desliga o cálculo sem pedidos)."""
        state = self._sessions.get(session_id)
        if state is None or state.wants.pop(connection_id, None) is None:
            return
        await self._sync_composites(session_id, state)

    async def _sync_composites(self, session_id: str, state: _SessionState) -> None:
        wanted = (
            any(s for s, _ in state.wants.values()),
            any(t for _, t in state.wants.values()),
        )
        if wanted == state.sent:
            return
        await self._send(
            session_id,
            {"type": "telemetry.config", "spectrum": wanted[0], "pressure_trace": wanted[1]},
        )
        state.sent = wanted

    def connections(self, session_id: str) -> int:
        state = self._sessions.get(session_id)
        return 0 if state is None else state.connections

    def realtime_factor(self, session_id: str) -> float | None:
        rt = self.runtime(session_id)
        return None if rt is None else rt.view.realtime_factor

    def run_active(self, session_id: str) -> bool:
        rt = self.runtime(session_id)
        return rt is not None and rt.view.active_run_id is not None

    # ------------------------------------------------------------------ comandos
    async def _send(self, session_id: str, command: dict[str, object]) -> None:
        rt = self.runtime(session_id)
        if self.dyno is None or rt is None:
            raise SimRemapError("Sessão encerrada.", code="SIM_WORKER_UNAVAILABLE")
        await self.dyno.send(rt, command)

    async def set_fps(self, session_id: str, fps: int) -> None:
        """``fps`` da sessão (último pedido vence) na próxima fronteira de frame."""
        state = self._state(session_id)
        if state.fps == fps or (state.fps is None and fps == self.default_fps):
            state.fps = fps
            return
        await self._send(session_id, {"type": "telemetry.config", "fps": fps})
        state.fps = fps

    async def throttle(self, session_id: str, throttle_pct: float) -> str | None:
        """``control.throttle``: só sem puxada ativa; devolve o ``code`` do erro ou ``None``."""
        if self.run_active(session_id):
            return "THROTTLE_LOCKED_BY_RUN"
        await self._send(session_id, {"type": "operator.throttle", "throttle_pct": throttle_pct})
        return None

    # ------------------------------------------------------------------ logs
    def _meta(self, session_id: str, run_id: str) -> SessionMeta | None:
        rt = self.runtime(session_id)
        if rt is None:
            return None
        run = rt.runs.get(run_id)
        view = rt.view
        return SessionMeta(
            vehicle_id=view.vehicle_id,
            profile_id=str(view.profile_id),
            fuel_id=str(view.fuel_id),
            seed=view.seed,
            calibration_hash=run.calibration_hash
            if run is not None
            else rt.calibration.content_hash,
        )

    async def run_state(self, run_id: str) -> str | None:
        """Estado da puxada (memória do dyno ou banco); ``None`` se não existe."""
        if self.dyno is None:
            return None
        run = await self.dyno.find_run(run_id)
        return None if run is None else run.state.value

    async def load_log(self, log_id: str, *, run: bool = False) -> LogData:
        """Log gravado (``run = True``: ``log_id`` é o ``run_id`` de um log simulado)."""
        repo = self.repository
        if repo is None:
            raise telemetry_error("LOG_NOT_FOUND", f"O log {log_id} não existe.")
        row = await repo.get(log_id)
        if row is not None:
            return await repo.load(row)
        if run:
            if self.logbook.is_pending(log_id):
                raise telemetry_error(
                    "LOG_NOT_READY", f"O log da puxada {log_id} ainda está a ser gravado."
                )
            memory = self.logbook.in_memory(log_id)
            if memory is not None:
                return await self.logbook.retry_memory(log_id) or memory
            state = await self.run_state(log_id)
            if state is None:
                raise telemetry_error("RUN_NOT_FOUND", f"A puxada {log_id} não existe.")
            if state not in {s.value for s in TERMINAL_RUN_STATES}:
                raise telemetry_error(
                    "LOG_NOT_READY", f"A puxada {log_id} ainda está em curso ({state})."
                )
        raise telemetry_error("LOG_NOT_FOUND", f"O log {log_id} não existe.", log_id=log_id)
