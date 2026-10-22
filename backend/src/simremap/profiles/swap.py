"""Máquina de estados da sessão de ECU e idempotência do swap (RF-17, RF-18; EC-01 a EC-03).

Estados (seção 8): ``oem`` → ``awaiting_base_setup`` (swap para standalone sem setup
mínimo ou sem mapa) → ``standalone_ready`` (base mínima ``ok`` e calibração aplicada);
``standalone_ready`` → ``awaiting_base_setup`` quando um PUT invalida um item obrigatório
(EC-06); qualquer estado → ``oem`` no swap de volta (snapshot e base de série).

``SwapPlan`` decide o que o serviço faz em cada transição (sem I/O):

- saída do OEM exige ``confirm_snapshot`` (EC-02) e grava o snapshot da calibração ativa;
- volta ao OEM repõe o snapshot (mesmo ``content_hash``) e mantém guardada a calibração
  standalone para um swap futuro (Fluxo D);
- entre standalone a ``BaseSetup`` é mantida e um mapa base novo é gerado quando o setup
  mínimo está completo (RF-18); do OEM para o mesmo perfil standalone de antes, a
  calibração standalone guardada é reaproveitada.

``SwapIdempotency``: mesmo ``request_id`` na mesma sessão devolve o mesmo ``SwapResult``
durante 10 min, sem novo snapshot (EC-03).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Final, Literal

from simremap.db.base import utcnow
from simremap.profiles.contracts import EcuState, SwapResult
from simremap.profiles.errors import profile_error

__all__ = [
    "IDEMPOTENCY_TTL",
    "MapAction",
    "SwapIdempotency",
    "SwapPlan",
    "plan_swap",
    "state_after_setup",
]

IDEMPOTENCY_TTL: Final = timedelta(minutes=10)
Family = Literal["oem", "standalone"]
MapAction = Literal["restore_snapshot", "reuse_standalone", "generate", "none"]


@dataclass(frozen=True, slots=True)
class SwapPlan:
    take_snapshot: bool
    map_action: MapAction
    ecu_state: EcuState


def plan_swap(
    *,
    current_profile: str,
    target_profile: str,
    current_family: Family,
    target_family: Family,
    confirm_snapshot: bool,
    minimum_valid: bool,
    stored_standalone_profile: str | None,
    swap_supported: bool,
) -> SwapPlan:
    """Plano da transição ou erro 422 (``SWAP_TARGET_INVALID``, ``SWAP_CONFIRMATION_REQUIRED``,
    ``SWAP_NOT_SUPPORTED_FOR_VEHICLE``)."""
    if target_profile == current_profile:
        raise profile_error(
            "SWAP_TARGET_INVALID",
            f"A sessão já usa o perfil {target_profile}.",
            target_profile_id=target_profile,
        )
    if target_family == "oem":
        return SwapPlan(take_snapshot=False, map_action="restore_snapshot", ecu_state="oem")
    if not swap_supported:
        raise profile_error(
            "SWAP_NOT_SUPPORTED_FOR_VEHICLE",
            "Este veículo não tem ficha de hardware para a troca de ECU.",
        )
    leaving_oem = current_family == "oem"
    if leaving_oem and not confirm_snapshot:
        raise profile_error(
            "SWAP_CONFIRMATION_REQUIRED",
            "Confirme o snapshot da calibração OEM (confirm_snapshot = true) antes da troca.",
        )
    if not minimum_valid:
        return SwapPlan(leaving_oem, "none", "awaiting_base_setup")
    if leaving_oem and stored_standalone_profile == target_profile:
        return SwapPlan(leaving_oem, "reuse_standalone", "standalone_ready")
    return SwapPlan(leaving_oem, "generate", "standalone_ready")


def state_after_setup(*, minimum_valid: bool, has_map: bool) -> EcuState:
    """Estado standalone depois de gravar a base (RF-19, RF-20, EC-06)."""
    return "standalone_ready" if minimum_valid and has_map else "awaiting_base_setup"


class SwapIdempotency:
    """Cache de ``SwapResult`` por ``(session_id, request_id)`` com validade de 10 min."""

    def __init__(self, clock: Callable[[], datetime] = utcnow, ttl: timedelta = IDEMPOTENCY_TTL):
        self._clock = clock
        self._ttl = ttl
        self._items: dict[tuple[str, str], tuple[datetime, SwapResult]] = {}
        self._lock = Lock()

    def get(self, session_id: str, request_id: str | None) -> SwapResult | None:
        if request_id is None:
            return None
        now = self._clock()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
            hit = self._items.get((session_id, request_id))
        return hit[1] if hit is not None else None

    def put(self, session_id: str, request_id: str | None, result: SwapResult) -> None:
        if request_id is None:
            return
        with self._lock:
            self._items[(session_id, request_id)] = (self._clock() + self._ttl, result)
