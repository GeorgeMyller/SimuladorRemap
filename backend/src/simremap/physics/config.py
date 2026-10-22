"""Validação do ``PhysicsConfig`` contra o veículo e passo fixo ``dt = 1 / sim_hz`` (RF-01; D-07).

O ``PhysicsConfig`` (contrato) já valida os seus limites (``sim_hz`` 100–1000, ``seed``,
constantes τ). Aqui ficam as verificações que exigem o ``VehicleSpec``/``FuelSpec`` e a
resolução dos padrões dependentes do veículo (wall-wetting ligado em PFI, desligado em GDI).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.physics.contracts import PhysicsConfig
from simremap.physics.errors import PHYSICS_CONFIG_INVALID, PHYSICS_DT_MISMATCH, PhysicsError

__all__ = ["ResolvedConfig", "check_dt", "resolve_config", "substeps"]

SUBSTEP_MAX_S = 1e-3  # s; subpasso máximo das integrações de gás (h = dt / ceil(dt / 1 ms))


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """``PhysicsConfig`` com os padrões resolvidos para um veículo concreto."""

    config: PhysicsConfig
    sim_hz: int
    dt: float  # s
    n_substeps: int
    h: float  # s, subpasso das integrações de gás
    wall_wetting: bool
    wideband_buffer_len: int  # ticks na fila de atraso de transporte da wideband


def substeps(dt: float) -> int:
    """``k = ceil(dt / 1 ms)`` com tolerância numérica (1 ms ⇒ 1 subpasso)."""
    return max(1, math.ceil(dt / SUBSTEP_MAX_S - 1e-9))


def check_dt(config: PhysicsConfig, dt: float) -> None:
    """Levanta ``PHYSICS_DT_MISMATCH`` se ``dt`` diferir de ``1/sim_hz`` acima de 1e-12 s."""
    if not (math.isfinite(dt) and config.dt_matches(dt)):
        raise PhysicsError(
            PHYSICS_DT_MISMATCH,
            f"dt={dt!r} difere de 1/sim_hz={config.dt!r} (tolerância 1e-12 s)",
            dt=dt,
            expected_dt=config.dt,
        )


def resolve_config(config: PhysicsConfig, vehicle: VehicleSpec, fuel: FuelSpec) -> ResolvedConfig:
    """Valida a combinação configuração × veículo × combustível (EC-09)."""
    n_cyl = vehicle.engine.n_cyl
    for fault in config.faults:
        if fault.cylinder is not None and fault.cylinder > n_cyl:
            raise PhysicsError(
                PHYSICS_CONFIG_INVALID,
                f"falha '{fault.kind}' no cilindro {fault.cylinder} > n_cyl={n_cyl}",
            )
        if fault.kind == "wastegate_stuck" and vehicle.turbo is None:
            raise PhysicsError(
                PHYSICS_CONFIG_INVALID,
                f"falha 'wastegate_stuck' exige turbo; '{vehicle.vehicle_id}' não tem turbo",
            )
    if fuel.afr_stoich <= 0.0 or fuel.lhv_mj_kg <= 0.0:
        raise PhysicsError(PHYSICS_CONFIG_INVALID, f"combustível '{fuel.fuel_id}' inválido")
    engine = vehicle.engine
    if engine.ivc_deg_abdc + engine.evo_deg_bbdc >= 180.0:  # noqa: PLR2004
        raise PhysicsError(PHYSICS_CONFIG_INVALID, "IVC e EVO deixam o ciclo fechado vazio")
    wall_wetting = (
        config.wall_wetting_enabled
        if config.wall_wetting_enabled is not None
        else engine.injection_type == "pfi"
    )
    dt = config.dt
    k = substeps(dt)
    # Atraso máximo da wideband: 0,02 s + 2·60/300 rpm = 0,42 s (abaixo de 300 rpm satura).
    buffer_len = math.ceil(0.45 * config.sim_hz) + 2
    return ResolvedConfig(
        config=config,
        sim_hz=config.sim_hz,
        dt=dt,
        n_substeps=k,
        h=dt / k,
        wall_wetting=wall_wetting,
        wideband_buffer_len=buffer_len,
    )
