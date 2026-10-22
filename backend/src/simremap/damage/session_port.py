"""Porta injetável entre os endpoints do dano e as sessões/puxadas do ``dyno-bench``.

O ``dyno-bench`` (dono de ``SimulationSession`` e ``DynoRun``) implementa
``DamageSessionPort`` e publica-o em ``app.state.damage_port``. Enquanto não existe,
vale ``NullSessionPort`` (nenhuma sessão: 404 ``SESSION_NOT_FOUND``).
``InProcessDamagePort`` serve o modo ``thread`` e os testes: guarda o ``DamageModel`` de
cada sessão no mesmo processo.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from simremap.core.errors import SimRemapError
from simremap.damage.contracts import EngineHealth
from simremap.damage.model import DamageModel
from simremap.dyno.contracts import DynoRun, SessionState

__all__ = [
    "DamageSessionPort",
    "InProcessDamagePort",
    "MechanicalReset",
    "NullSessionPort",
    "SessionView",
]


@dataclass(frozen=True, slots=True)
class SessionView:
    """Vista mínima da ``SimulationSession`` usada pelos endpoints do dano."""

    session_id: str
    vehicle_id: str
    state: SessionState
    damage_enabled: bool = True
    active_run_id: str | None = None
    t_sim_s: float = 0.0
    last_forensic_report_url: str | None = None

    @property
    def closed(self) -> bool:
        return self.state == "closed"


class DamageSessionPort(Protocol):
    async def get_session(self, session_id: str) -> SessionView | None: ...

    async def get_run(self, run_id: str) -> DynoRun | None: ...

    async def live_health(self, session_id: str, include_failures: bool) -> EngineHealth | None:
        """Saúde ao vivo do worker; ``None`` se o worker estiver indisponível (EC-13)."""
        ...

    async def restore_engine(self, session_id: str, note: str | None) -> EngineHealth:
        """Comando ``engine.restore`` (``DamageModel.restore`` + ``reset_mechanical``)."""
        ...

    async def rod_weights(self, session_id: str) -> list[float]: ...


class MechanicalReset(Protocol):
    def reset_mechanical(self) -> None: ...


class NullSessionPort:
    """Porta sem sessões (``dyno-bench`` ainda não integrado)."""

    async def get_session(self, session_id: str) -> SessionView | None:
        return None

    async def get_run(self, run_id: str) -> DynoRun | None:
        return None

    async def live_health(self, session_id: str, include_failures: bool) -> EngineHealth | None:
        return None

    async def restore_engine(self, session_id: str, note: str | None) -> EngineHealth:
        raise SimRemapError("Worker de simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")

    async def rod_weights(self, session_id: str) -> list[float]:
        return []


@dataclass(slots=True)
class _Entry:
    view: SessionView
    model: DamageModel | None
    physics: MechanicalReset | None


class InProcessDamagePort:
    """Registo em memória de sessões, modelos de dano e puxadas."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Entry] = {}
        self._runs: dict[str, DynoRun] = {}

    def register_session(
        self,
        view: SessionView,
        model: DamageModel | None,
        physics: MechanicalReset | None = None,
    ) -> None:
        self._sessions[view.session_id] = _Entry(view, model, physics)

    def update_session(self, session_id: str, **changes: object) -> None:
        entry = self._sessions[session_id]
        entry.view = replace(entry.view, **changes)  # type: ignore[arg-type]

    def detach_worker(self, session_id: str) -> None:
        """Simula a morte do worker: o modelo deixa de estar acessível."""
        self._sessions[session_id].model = None

    def register_run(self, run: DynoRun) -> None:
        self._runs[run.run_id] = run

    async def get_session(self, session_id: str) -> SessionView | None:
        entry = self._sessions.get(session_id)
        return None if entry is None else entry.view

    async def get_run(self, run_id: str) -> DynoRun | None:
        return self._runs.get(run_id)

    async def live_health(self, session_id: str, include_failures: bool) -> EngineHealth | None:
        entry = self._sessions.get(session_id)
        if entry is None or entry.model is None:
            return None
        return entry.model.engine_health(
            include_failures=include_failures,
            last_forensic_report_url=entry.view.last_forensic_report_url,
        )

    async def restore_engine(self, session_id: str, note: str | None) -> EngineHealth:
        entry = self._sessions.get(session_id)
        if entry is None or entry.model is None:
            raise SimRemapError("Worker de simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")
        entry.model.restore()
        if entry.physics is not None:
            entry.physics.reset_mechanical()
        if entry.view.state == "engine_locked":
            entry.view = replace(entry.view, state="ready")
        return entry.model.engine_health(
            last_forensic_report_url=entry.view.last_forensic_report_url
        )

    async def rod_weights(self, session_id: str) -> list[float]:
        entry = self._sessions.get(session_id)
        return [] if entry is None or entry.model is None else entry.model.rod_weights
