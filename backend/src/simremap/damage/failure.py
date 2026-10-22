"""Mapeamento saúde → falha e emissão de ``FailureEvent`` (RF-10, RF-18; Apêndice B.8).

Componentes por veículo (ordem canônica): ``piston:1..n``, ``rod:1..n``, ``valves:1..n``,
``head_gasket``, ``bearings`` e ``turbo:turbine`` (só com turbo).

Os ``failure_event_id`` são ULID determinísticos: carimbo de 48 bits = ``t_sim`` em ms e
80 bits do SHA-256 de ``(session_id, seed, tick, component_id, sequência)``. Assim duas
execuções iguais geram os mesmos ids (e o mesmo ``report_sha256``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from simremap.damage.contracts import (
    ComponentKind,
    FailureEvent,
    FailureMechanism,
    FailureMode,
)

__all__ = [
    "CAUSES",
    "ComponentSpec",
    "build_components",
    "build_failure_event",
    "classify_failure",
    "classify_warning",
    "dominant_cause",
    "make_ulid",
]

CAUSES: Final = ("knock", "thermal", "overload", "overrev", "preignition", "pressure")
_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    component_id: str
    kind: ComponentKind
    cylinder: int | None


def build_components(n_cyl: int, has_turbo: bool) -> list[ComponentSpec]:
    """RF-10: 3 componentes por cilindro + junta + bronzinas (+ turbina)."""
    specs: list[ComponentSpec] = []
    kinds: tuple[ComponentKind, ...] = ("piston", "rod", "valves")
    for kind in kinds:
        specs.extend(ComponentSpec(f"{kind}:{i}", kind, i) for i in range(1, n_cyl + 1))
    specs.append(ComponentSpec("head_gasket", "head_gasket", None))
    specs.append(ComponentSpec("bearings", "bearings", None))
    if has_turbo:
        specs.append(ComponentSpec("turbo:turbine", "turbine", None))
    return specs


def dominant_cause(damage_by_cause: Mapping[str, float]) -> str | None:
    """Causa com maior parcela de dano (empate: ordem de ``CAUSES``)."""
    best: str | None = None
    best_value = 0.0
    for cause in CAUSES:
        value = damage_by_cause.get(cause, 0.0)
        if value > best_value:
            best, best_value = cause, value
    return best


def classify_failure(  # noqa: PLR0911
    kind: ComponentKind,
    damage_by_cause: Mapping[str, float],
    preignition_kind: str | None = None,
) -> tuple[FailureMode, FailureMechanism]:
    """Modo e mecanismo de uma falha catastrófica (health 0) pelo Apêndice B.8."""
    cause = dominant_cause(damage_by_cause)
    if kind == "piston":
        if cause == "thermal":
            return FailureMode.PISTON_FAILURE, FailureMechanism.PISTON_THERMAL_MELT
        if cause == "preignition":
            mechanism = (
                FailureMechanism.LSPI
                if preignition_kind == "lspi"
                else FailureMechanism.HOT_SPOT_PREIGNITION
            )
            return FailureMode.PRE_IGNITION, mechanism
        if cause == "overrev":
            return FailureMode.PISTON_FAILURE, FailureMechanism.VALVE_PISTON_CONTACT
        return FailureMode.PISTON_FAILURE, FailureMechanism.KNOCK_EROSION
    if kind == "head_gasket":
        return FailureMode.KNOCK_DAMAGE, FailureMechanism.HEAD_GASKET_BREACH
    if kind == "valves":
        if cause == "overrev":
            return FailureMode.PISTON_FAILURE, FailureMechanism.VALVE_PISTON_CONTACT
        return FailureMode.EGT_OVERTEMP, FailureMechanism.EXHAUST_VALVE_BURN
    if kind == "rod":
        return FailureMode.ROD_FAILURE, FailureMechanism.ROD_OVERLOAD
    if kind == "bearings":
        return FailureMode.ROD_FAILURE, FailureMechanism.BEARING_SPIN
    if cause == "overrev":
        return FailureMode.TURBO_MELTDOWN, FailureMechanism.TURBO_OVERSPEED_BURST
    return FailureMode.TURBO_MELTDOWN, FailureMechanism.TURBINE_CREEP


def classify_warning(
    kind: ComponentKind,
    damage_by_cause: Mapping[str, float],
    preignition_kind: str | None = None,
) -> tuple[FailureMode, FailureMechanism]:
    """Aviso não catastrófico (health ≤ 0,50 pela 1.ª vez)."""
    if kind == "piston" and dominant_cause(damage_by_cause) in (None, "knock"):
        return FailureMode.KNOCK_DAMAGE, FailureMechanism.RING_LAND_CRACK
    return classify_failure(kind, damage_by_cause, preignition_kind)


def _encode_crockford(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def make_ulid(timestamp_ms: int, *parts: object) -> str:
    """ULID determinístico (26 caracteres Crockford) a partir de um carimbo e de partes."""
    seed = "|".join(str(p) for p in parts).encode("utf-8")
    rand = int.from_bytes(hashlib.sha256(seed).digest()[:10], "big")
    value = ((timestamp_ms & ((1 << 48) - 1)) << 80) | rand
    return _encode_crockford(value, 26)


def build_failure_event(
    *,
    session_id: str,
    run_id: str | None,
    seed: int,
    tick: int,
    t_sim_s: float,
    sequence: int,
    spec: ComponentSpec,
    mode: FailureMode,
    mechanism: FailureMechanism,
    catastrophic: bool,
    simulated_only: bool,
    health_after: float,
    causal_variables: Mapping[str, float],
) -> FailureEvent:
    """Monta o ``FailureEvent`` com id determinístico."""
    event_id = make_ulid(
        round(t_sim_s * 1000.0), session_id, seed, tick, spec.component_id, sequence
    )
    return FailureEvent(
        failure_event_id=event_id,
        session_id=session_id,
        run_id=run_id,
        tick=tick,
        t_sim_s=t_sim_s,
        cylinder=spec.cylinder,
        component_id=spec.component_id,
        mode=mode,
        mechanism=mechanism,
        catastrophic=catastrophic,
        simulated_only=simulated_only,
        health_after=min(1.0, max(0.0, health_after)),
        causal_variables={k: float(v) for k, v in causal_variables.items()},
    )
