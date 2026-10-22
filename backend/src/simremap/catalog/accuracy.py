"""Varredura headless de referência pela física (vehicle-catalog RF-21, RF-29; D-30; T266).

Protocolo (igual ao ``test_catalog_reference_curve`` do engine-physics-core):

- ``PhysicsEngine`` com ``sim_hz = 500``, ruído desligado e motor quente (ECT 90 °C);
- piloto ``ReferenceDriver`` em malha aberta sobre o ``reference_command_schedule`` do
  veículo (sem ECU) e banco ``RpmHoldRig`` que segura a rotação;
- pontos da curva de série de 2000 rpm até à rotação máxima da curva, passo de 250 rpm,
  em ordem crescente com o mesmo motor (9 s no 1.º ponto, 4 s nos seguintes) e média
  dos últimos 0,3 s;
- a série simulada (torque na cambota, potência na roda, λ do coletor, EGT do coletor em
  °C) é comparada com ``compare_to_reference`` (desvio < ``tolerance_pct`` = 5 %).

Tudo é determinístico (física semeada e sem relógio de parede): a mesma entrada dá a
mesma série e o mesmo ``max_deviation_pct`` bit a bit.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from simremap.catalog.compare import compare_to_reference
from simremap.catalog.contracts import (
    FuelSpec,
    ReferenceComparison,
    ReferenceCurve,
    ReferenceCurvePoint,
    VehicleSpec,
)
from simremap.catalog.loader import Catalog
from simremap.physics.contracts import EngineState, PhysicsConfig
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig

__all__ = [
    "ACCURACY_SIM_HZ",
    "SWEEP_START_RPM",
    "AccuracyResult",
    "SweepPoint",
    "reference_sweep",
    "run_accuracy",
    "sweep_rpms",
]

ACCURACY_SIM_HZ: Final = 500  # Hz
SWEEP_START_RPM: Final = 2000.0  # rev/min
FIRST_POINT_S: Final = 9.0  # s (enchimento do turbo a partir do repouso)
POINT_S: Final = 4.0  # s
AVERAGE_S: Final = 0.3  # s
WARM_ECT_C: Final = 90.0  # °C
LAMBDA_RANGE: Final = (0.6, 1.3)  # limites do ReferenceCurvePoint
EGT_RANGE_C: Final = (200.0, 1100.0)


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """Médias de regime permanente num RPM da varredura."""

    rpm: float
    torque_crank_nm: float
    power_wheel_kw: float
    lambda_value: float
    egt_c: float
    map_kpa: float
    theta_pmax_deg_atdc: float
    p_max_bar: float  # máximo do último tick, entre cilindros
    piston_temp_c: float  # máximo do último tick, entre cilindros
    turbo_rpm: float | None

    def as_curve_point(self) -> ReferenceCurvePoint:
        lam = min(max(self.lambda_value, LAMBDA_RANGE[0]), LAMBDA_RANGE[1])
        egt = min(max(self.egt_c, EGT_RANGE_C[0]), EGT_RANGE_C[1])
        return ReferenceCurvePoint(
            rpm=self.rpm,
            torque_crank_nm=max(self.torque_crank_nm, 0.0),
            power_wheel_kw=max(self.power_wheel_kw, 0.0),
            lambda_value=lam,
            egt_c=egt,
        )


@dataclass(frozen=True, slots=True)
class AccuracyResult:
    vehicle_id: str
    curve_id: str
    points: tuple[SweepPoint, ...]
    comparison: ReferenceComparison

    @property
    def max_deviation_pct(self) -> float:
        return max(d.max_deviation_pct for d in self.comparison.deviations)

    @property
    def peak_whp(self) -> float:
        return max(p.power_wheel_kw for p in self.points) / 0.7457


def sweep_rpms(curve: ReferenceCurve, start_rpm: float = SWEEP_START_RPM) -> list[float]:
    """RPM da curva a partir de ``start_rpm`` (passo da curva: 250 rpm)."""
    return [p.rpm for p in curve.points if p.rpm >= start_rpm]


def _hold(engine: PhysicsEngine, driver: ReferenceDriver, rpm: float, seconds: float) -> SweepPoint:
    dt = engine.resolved.dt
    rig = RpmHoldRig(target_rpm=rpm)
    engine.crank(rpm)
    n = round(seconds / dt)
    n_avg = max(1, round(AVERAGE_S / dt))
    acc = [0.0] * 6
    state: EngineState | None = None
    for k in range(n):
        sensors = engine.read_sensors()
        commands = driver.commands(sensors, dt)
        state = engine.step(commands, rig.load(state, engine.rpm, dt), dt)
        if k >= n - n_avg:
            acc[0] += state.torque_nm
            acc[1] += state.wheel_power_kw
            acc[2] += state.lambda_collector or 0.0
            acc[3] += state.egt_collector_c
            acc[4] += state.map_kpa
            acc[5] += sum(state.theta_pmax_deg_atdc) / len(state.theta_pmax_deg_atdc)
    if state is None:
        raise ValueError("duração da varredura menor que um passo")
    avg = [a / n_avg for a in acc]
    return SweepPoint(
        rpm=rpm,
        torque_crank_nm=avg[0],
        power_wheel_kw=avg[1],
        lambda_value=avg[2],
        egt_c=avg[3],
        map_kpa=avg[4],
        theta_pmax_deg_atdc=avg[5],
        p_max_bar=max(state.p_max_kpa) / 100.0,
        piston_temp_c=max(state.piston_temp_c),
        turbo_rpm=state.turbo_rpm,
    )


def reference_sweep(
    vehicle: VehicleSpec,
    fuel: FuelSpec,
    rpms: Sequence[float],
    *,
    sim_hz: int = ACCURACY_SIM_HZ,
    first_point_s: float = FIRST_POINT_S,
    point_s: float = POINT_S,
) -> list[SweepPoint]:
    """Varredura a plena carga em regime permanente, em ordem crescente de ``rpms``."""
    if not rpms or any(b <= a for a, b in itertools.pairwise(rpms)):
        raise ValueError("rpms deve ser não vazio e estritamente crescente")
    engine = PhysicsEngine(
        PhysicsConfig(sim_hz=sim_hz, noise_enabled=False), vehicle, fuel, initial_ect_c=WARM_ECT_C
    )
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule)
    return [
        _hold(engine, driver, rpm, first_point_s if i == 0 else point_s)
        for i, rpm in enumerate(rpms)
    ]


def run_accuracy(
    catalog: Catalog, vehicle_id: str, *, sim_hz: int = ACCURACY_SIM_HZ
) -> AccuracyResult:
    """Varre o veículo com o combustível de série e compara com a sua 1.ª curva de série."""
    entry = catalog.vehicles.get(vehicle_id)
    if entry is None:
        raise KeyError(vehicle_id)
    spec = entry.spec
    curve = entry.curves[0]
    fuel = catalog.fuels[curve.fuel_id]
    points = reference_sweep(spec, fuel, sweep_rpms(curve), sim_hz=sim_hz)
    comparison = compare_to_reference(curve, [p.as_curve_point() for p in points])
    return AccuracyResult(vehicle_id, curve.curve_id, tuple(points), comparison)
