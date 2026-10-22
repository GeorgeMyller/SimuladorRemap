"""Guardas do ``POST /api/v1/sessions/{session_id}/runs`` antes do ``run.start`` (T416).

Ordem (rest-api E-09): sessão encerrada (409 ``SESSION_CLOSED``) → motor bloqueado
(409 ``ENGINE_DESTROYED``, ``detail`` aponta o ``engine/restore``; RF-20) → puxada ativa
(409 ``RUN_IN_PROGRESS``; RF-21) → setup da ECU (409 ``ECU_SETUP_INCOMPLETE`` com
``pending``, via ``ProfileSessionGuard``; D-REST-06) → sonda sem ``attempt_id``
(422 ``PROBE_NOT_ALLOWED``; RF-26) → marcha (422 ``GEAR_NOT_AVAILABLE``) → faixa de
rotação (422 ``RPM_RANGE_INVALID``: ``end_rpm ≤ start_rpm + 500`` depois do limite do
``rev_limit_rpm``; células acima do corte).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from simremap.dyno.contracts import MIN_RPM_SPAN, DynoRunRequest, RunType
from simremap.dyno.errors import dyno_error

__all__ = ["ProfileSessionGuard", "RunGuardInput", "check_run_allowed", "restore_url"]


@runtime_checkable
class ProfileSessionGuard(Protocol):
    """Guarda do ``ecu-profiles``: itens pendentes do setup (vazio = pode arrancar)."""

    def can_start_run(self, session_id: str) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class RunGuardInput:
    """Estado da sessão relevante para aceitar uma puxada."""

    session_id: str
    closed: bool
    engine_locked: bool
    active_run_id: str | None
    attempt_id: str | None
    n_gears: int
    rev_limit_rpm: float


def restore_url(session_id: str) -> str:
    return f"/api/v1/sessions/{session_id}/engine/restore"


def _check_rpm(request: DynoRunRequest, rev_limit: float) -> None:
    if request.run_type == RunType.STEADY_STATE_HOLD:
        above = [c.rpm for c in request.cells if c.rpm > rev_limit]
        if above:
            raise dyno_error(
                "RPM_RANGE_INVALID",
                f"Células acima do corte de rotação ({rev_limit:.0f} rpm): "
                + ", ".join(f"{r:.0f}" for r in above[:8]),
                rev_limit_rpm=rev_limit,
            )
        return
    if not request.rpm_range_ok(rev_limit):
        end = request.effective_end_rpm(rev_limit)
        raise dyno_error(
            "RPM_RANGE_INVALID",
            f"end_rpm efetivo {end:.0f} deve ser maior que start_rpm + {MIN_RPM_SPAN:.0f} "
            f"({request.start_rpm + MIN_RPM_SPAN:.0f} rpm).",
            start_rpm=request.start_rpm,
            end_rpm=end,
            rev_limit_rpm=rev_limit,
        )


def check_run_allowed(
    state: RunGuardInput,
    request: DynoRunRequest,
    *,
    pending_setup: Sequence[str] = (),
) -> None:
    """Lança o ``DynoError`` da primeira regra violada; não devolve nada se aceitar."""
    sid = state.session_id
    if state.closed:
        raise dyno_error("SESSION_CLOSED", f"A sessão {sid} está encerrada.", session_id=sid)
    if state.engine_locked:
        raise dyno_error(
            "ENGINE_DESTROYED",
            f"O motor da sessão está destruído; restaure-o com POST {restore_url(sid)}.",
            restore_url=restore_url(sid),
        )
    if state.active_run_id is not None:
        raise dyno_error(
            "RUN_IN_PROGRESS",
            f"A puxada {state.active_run_id} ainda está em andamento.",
            active_run_id=state.active_run_id,
        )
    if pending_setup:
        raise dyno_error(
            "ECU_SETUP_INCOMPLETE",
            "O setup base da ECU tem itens pendentes: " + ", ".join(pending_setup),
            pending=list(pending_setup),
        )
    if request.probe is not None and state.attempt_id is None:
        raise dyno_error(
            "PROBE_NOT_ALLOWED",
            "Puxadas de sonda só são aceitas em sessões abertas por uma tentativa.",
        )
    if request.gear > state.n_gears:
        raise dyno_error(
            "GEAR_NOT_AVAILABLE",
            f"O veículo tem {state.n_gears} marchas; a {request.gear}.ª não existe.",
            n_gears=state.n_gears,
        )
    _check_rpm(request, state.rev_limit_rpm)
