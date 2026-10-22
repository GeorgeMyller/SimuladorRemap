"""``CompiledCalibration`` e ``EcuHardwareConfig`` para o hot path.

Fontes: ecu-core RNF-01; simulation-bus 3.2.

A compilação converte a ``Calibration`` (Pydantic) em listas Python e índices de entrada:
cada tabela guarda o índice da grandeza do eixo no vetor ``inputs`` do tick, por isso a
ECU genérica aceita qualquer ``AxisQuantity`` nos eixos (ex.: ``load_pct`` no perfil OEM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from simremap.ecu.calibration import CalibrationContent, FuelModelConfig, compute_content_hash
from simremap.ecu.contracts import AxisQuantity, StrategyConfig, TableKind
from simremap.ecu.limits import PER_CYLINDER_KINDS
from simremap.ecu.tables import Table2D, Table3D, interp1, interp2

if TYPE_CHECKING:
    from simremap.catalog.contracts import FuelSpec, VehicleSpec

__all__ = [
    "N_INPUTS",
    "QUANTITY_INDEX",
    "CompiledCalibration",
    "CompiledTable1D",
    "CompiledTable2D",
    "EcuHardwareConfig",
    "compile_calibration",
]

QUANTITY_INDEX: Final[dict[AxisQuantity, int]] = {q: i for i, q in enumerate(AxisQuantity)}
"""Posição de cada grandeza no vetor ``inputs`` do tick."""
N_INPUTS: Final = len(QUANTITY_INDEX)


@dataclass(frozen=True, slots=True)
class EcuHardwareConfig:
    """Hardware visto pela ECU.

    Vazão, ΔP de referência, dead time, AFR, densidade, ``n_cyl`` e cilindrada.

    Vem da ``BaseSetup`` (standalone) ou do catálogo (OEM) — ecu-profiles OQ-01.
    """

    n_cyl: int
    displacement_cc: float  # cc
    injector_flow_cc_min: float  # cc/min a ref_pressure_kpa
    afr_stoich: float  # (-)
    fuel_density_g_cc: float  # g/cc
    ref_pressure_kpa: float = 300.0  # kPa (ΔP de referência do bico)
    dead_time_v: tuple[float, ...] = (8.0, 10.0, 12.0, 13.5, 14.5, 16.0)  # V
    dead_time_ms: tuple[float, ...] = (0.9, 0.9, 0.9, 0.9, 0.9, 0.9)  # ms
    use_rail_pressure: bool = True  # corrige a vazão por sqrt(ΔP_real / ΔP_ref)

    def __post_init__(self) -> None:
        if not 1 <= self.n_cyl <= 8:  # noqa: PLR2004
            raise ValueError("n_cyl deve estar entre 1 e 8")
        if self.displacement_cc <= 0 or self.injector_flow_cc_min <= 0:
            raise ValueError("cilindrada e vazão do bico devem ser positivas")
        if self.afr_stoich <= 0 or self.fuel_density_g_cc <= 0 or self.ref_pressure_kpa <= 0:
            raise ValueError("AFR, densidade e ΔP de referência devem ser positivos")
        if len(self.dead_time_v) != len(self.dead_time_ms) or len(self.dead_time_v) < 2:  # noqa: PLR2004
            raise ValueError("dead_time_v e dead_time_ms devem ter o mesmo tamanho (≥ 2)")
        if any(b <= a for a, b in zip(self.dead_time_v, self.dead_time_v[1:], strict=False)):
            raise ValueError("dead_time_v deve ser estritamente crescente")

    @property
    def v_cyl_m3(self) -> float:
        """Volume por cilindro (m³)."""
        return self.displacement_cc / self.n_cyl * 1e-6

    @property
    def q_inj_ref_g_ms(self) -> float:
        """Vazão mássica do bico a ΔP de referência (g/ms)."""
        return self.injector_flow_cc_min * self.fuel_density_g_cc / 60000.0

    def dead_time(self, battery_v: float) -> float:
        return interp1(self.dead_time_v, self.dead_time_ms, battery_v)

    @classmethod
    def from_vehicle(cls, vehicle: VehicleSpec, fuel: FuelSpec) -> EcuHardwareConfig:
        """Hardware de série do catálogo: dead time na linha de ΔP mais próxima da referência."""
        inj = vehicle.injectors
        grid = inj.dead_time_ms
        ys = grid.y_values
        row = min(range(len(ys)), key=lambda i: abs(ys[i] - inj.dp_ref_kpa))
        return cls(
            n_cyl=vehicle.engine.n_cyl,
            displacement_cc=vehicle.engine.displacement_cc,
            injector_flow_cc_min=inj.flow_cc_min * inj.count_per_cyl,
            afr_stoich=fuel.afr_stoich,
            fuel_density_g_cc=fuel.density_kg_m3 / 1000.0,
            ref_pressure_kpa=inj.dp_ref_kpa,
            dead_time_v=tuple(grid.x_values),
            dead_time_ms=tuple(grid.z_values[row]),
        )


@dataclass(slots=True)
class CompiledTable1D:
    qx: int
    xs: list[float]
    vs: list[float]

    def at(self, inputs: list[float]) -> float:
        return interp1(self.xs, self.vs, inputs[self.qx])


@dataclass(slots=True)
class CompiledTable2D:
    qx: int
    qy: int
    xs: list[float]
    ys: list[float]
    z: list[list[float]]

    def at(self, inputs: list[float]) -> float:
        return interp2(self.xs, self.ys, self.z, inputs[self.qx], inputs[self.qy])


CompiledTable = CompiledTable1D | CompiledTable2D


@dataclass(slots=True)
class CompiledCalibration:
    """Calibração pronta para o laço (listas Python, sem Pydantic no hot path)."""

    calibration_id: str
    version: int
    content_hash: str
    vehicle_id: str
    profile_id: str
    n_cyl: int
    fuel_mode: Literal["speed_density_ve", "direct_pulse_ms", "profile_air_model"]
    charge_temp_blend: float
    accel_enrich_tau_s: float
    afterstart_decay_s: float
    cranking_rpm: float
    cranking_ign_deg: float
    inj_duty_warn_pct: float
    tables: dict[TableKind, CompiledTable]
    fuel_trim_cyl: list[CompiledTable | None]
    ign_trim_cyl: list[CompiledTable | None]
    strategies: dict[str, StrategyConfig]
    profile_params: dict[str, float | bool | str]
    content: CalibrationContent = field(repr=False)
    live_table_ids: frozenset[str] = frozenset()

    def get(self, kind: TableKind) -> CompiledTable | None:
        return self.tables.get(kind)


def _compile_table(table: object) -> CompiledTable:
    if isinstance(table, Table3D):
        return CompiledTable2D(
            qx=QUANTITY_INDEX[table.x.quantity],
            qy=QUANTITY_INDEX[table.y.quantity],
            xs=list(table.x.values),
            ys=list(table.y.values),
            z=[list(row) for row in table.values],
        )
    if not isinstance(table, Table2D):  # pragma: no cover - AnyTable só tem 2 tipos
        raise TypeError(type(table).__name__)
    return CompiledTable1D(
        qx=QUANTITY_INDEX[table.x.quantity], xs=list(table.x.values), vs=list(table.values)
    )


def compile_calibration(
    content: CalibrationContent,
    n_cyl: int,
    *,
    calibration_id: str = "uncompiled",
    version: int = 1,
    content_hash: str | None = None,
) -> CompiledCalibration:
    """Compila ``content`` para ``n_cyl`` cilindros.

    Tabelas por cilindro com ``cylinder > n_cyl`` são ignoradas (não há o cilindro).
    ``content_hash`` omitido é recalculado.
    """
    if not 1 <= n_cyl <= 8:  # noqa: PLR2004
        raise ValueError("n_cyl deve estar entre 1 e 8")
    tables: dict[TableKind, CompiledTable] = {}
    fuel_trim: list[CompiledTable | None] = [None] * n_cyl
    ign_trim: list[CompiledTable | None] = [None] * n_cyl
    live: set[str] = set()
    for table_id, table in content.tables.items():
        if table.live_tunable:
            live.add(table_id)
        compiled = _compile_table(table)
        if table.kind in PER_CYLINDER_KINDS:
            cyl = (table.cylinder or 0) - 1
            if 0 <= cyl < n_cyl:
                target = fuel_trim if table.kind == TableKind.FUEL_TRIM_CYL else ign_trim
                target[cyl] = compiled
            continue
        tables[table.kind] = compiled
    fm: FuelModelConfig = content.fuel_model
    return CompiledCalibration(
        calibration_id=calibration_id,
        version=version,
        content_hash=content_hash or compute_content_hash(content),
        vehicle_id=content.vehicle_id,
        profile_id=content.profile_id.value,
        n_cyl=n_cyl,
        fuel_mode=fm.mode,
        charge_temp_blend=fm.charge_temp_blend,
        accel_enrich_tau_s=fm.accel_enrich_tau_s,
        afterstart_decay_s=fm.afterstart_decay_s,
        cranking_rpm=fm.cranking_rpm,
        cranking_ign_deg=fm.cranking_ign_deg,
        inj_duty_warn_pct=fm.inj_duty_warn_pct,
        tables=tables,
        fuel_trim_cyl=fuel_trim,
        ign_trim_cyl=ign_trim,
        strategies=dict(content.strategies),
        profile_params=dict(content.profile_params),
        content=content,
        live_table_ids=frozenset(live),
    )
