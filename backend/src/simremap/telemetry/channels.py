"""Catálogo de canais da telemetria expandido por cilindro (tel RF-04, RF-06; D-20).

A ordem do catálogo é a ordem das colunas do ``DataLog`` e do vetor de valores do
``TelemetrySampler``. Canais por cilindro expandem-se como ``<base>_cyl<k>`` (k = 1..n_cyl)
no lugar do grupo. O catálogo depende só de ``n_cyl`` e da presença de turbo (canal de
saúde da turbina); ``turbo_rpm`` e ``wastegate_duty_pct`` existem sempre e são nulos em
motores sem turbo (EC-19).

Canais compostos (fora do log): ``knock_spectrum`` e ``cyl_pressure_trace``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import Final

import numpy as np

from simremap.catalog.contracts import VehicleSpec
from simremap.telemetry.contracts import (
    Aggregation,
    ChannelKind,
    TelemetryChannel,
    channel_name,
)

__all__ = [
    "AGG_CODES",
    "COMPOSITE_CHANNELS",
    "ChannelCatalog",
    "build_catalog",
    "catalog_for_vehicle",
]

COMPOSITE_CHANNELS: Final = frozenset({"knock_spectrum", "cyl_pressure_trace"})

AGG_CODES: Final[dict[Aggregation, int]] = {
    Aggregation.LAST: 0,
    Aggregation.MAX: 1,
    Aggregation.MIN: 2,
    Aggregation.ANY: 3,
    Aggregation.SUM: 4,
}


@dataclass(frozen=True, slots=True)
class _Spec:
    base: str
    unit: str
    aggregation: Aggregation
    decimals: int
    source: str
    per_cylinder: bool = False
    flag: bool = False
    nullable: bool = False
    min_value: float | None = None
    max_value: float | None = None
    turbo_only: bool = False


_L, _MX, _MN, _ANY, _SUM = (
    Aggregation.LAST,
    Aggregation.MAX,
    Aggregation.MIN,
    Aggregation.ANY,
    Aggregation.SUM,
)

_SPECS: Final[tuple[_Spec, ...]] = (
    _Spec("rpm", "rpm", _L, 0, "EngineState.rpm", min_value=0.0),
    _Spec("map_kpa", "kPa", _L, 1, "SensorReadings.map_kpa", min_value=0.0),
    _Spec("baro_kpa", "kPa", _L, 1, "SensorReadings.baro_kpa", min_value=0.0),
    _Spec("boost_bar", "bar", _L, 2, "(SensorReadings.map_kpa-baro_kpa)/100"),
    _Spec("lambda", "-", _L, 3, "média de EngineState.lambda_cyl não nulos", nullable=True),
    _Spec("lambda_measured", "-", _L, 3, "SensorReadings.lambda_measured", min_value=0.5),
    _Spec("afr", "-", _L, 2, "lambda*FuelSpec.afr_stoich", nullable=True),
    _Spec("lambda", "-", _L, 3, "EngineState.lambda_cyl[k-1]", per_cylinder=True, nullable=True),
    _Spec("spark_deg", "°BTDC", _L, 1, "ActuatorCommands.ignition_advance_deg[k-1]", True),
    _Spec(
        "knock_sensor_v",
        "V",
        _MX,
        3,
        "SensorReadings.knock_sensor_v[k-1]",
        True,
        min_value=0.0,
        max_value=5.0,
    ),
    _Spec(
        "knock_intensity",
        "-",
        _MX,
        3,
        "SensorReadings.knock_intensity[k-1]",
        True,
        min_value=0.0,
        max_value=1.0,
    ),
    _Spec("knock_retard_deg", "°", _MX, 1, "max(EcuStatus.knock_retard_deg)", min_value=0.0),
    _Spec("knock_retard_deg", "°", _MX, 1, "EcuStatus.knock_retard_deg[k-1]", True),
    _Spec("cyl_pressure_peak_bar", "bar", _MX, 1, "EngineState.p_max_kpa[k-1]/100", True),
    _Spec("cyl_pressure_peak_bar", "bar", _MX, 1, "max(EngineState.p_max_kpa)/100"),
    _Spec("egt_c", "°C", _MX, 0, "SensorReadings.egt_c[k-1]", True),
    _Spec("egt_c", "°C", _MX, 0, "max(SensorReadings.egt_c)"),
    _Spec("egt_pre_turbo_c", "°C", _MX, 0, "SensorReadings.egt_collector_c"),
    _Spec("iat_c", "°C", _L, 1, "SensorReadings.iat_c"),
    _Spec("ect_c", "°C", _L, 1, "SensorReadings.ect_c"),
    _Spec("oil_temp_c", "°C", _L, 1, "SensorReadings.oil_temp_c"),
    _Spec("turbo_rpm", "rpm", _L, 0, "SensorReadings.turbo_rpm", nullable=True),
    _Spec("wastegate_duty_pct", "%", _L, 1, "ActuatorCommands.wastegate_duty_pct", nullable=True),
    _Spec("injector_duty_pct", "%", _MX, 1, "EcuStatus.inj_duty_pct", min_value=0.0),
    _Spec("injector_pw_ms", "ms", _MX, 2, "ActuatorCommands.injector_pw_ms[k-1]", True),
    _Spec("torque_nm", "N·m", _L, 1, "EngineState.torque_nm"),
    _Spec("power_kw", "kW", _L, 2, "EngineState.power_kw"),
    _Spec("whp", "hp", _L, 1, "EngineState.whp"),
    _Spec("throttle_pct", "%", _L, 1, "SensorReadings.tps_pct", min_value=0.0, max_value=100.0),
    _Spec("pedal_pct", "%", _L, 1, "DynoLoad.pedal_pct", min_value=0.0, max_value=100.0),
    _Spec("load_pct", "%", _L, 1, "EcuStatus.load_pct", nullable=True),
    _Spec("torque_request_nm", "N·m", _L, 1, "EcuStatus.torque_request_nm", nullable=True),
    _Spec("lambda_target", "-", _L, 3, "EcuStatus.lambda_target"),
    _Spec("boost_target_kpa", "kPa", _L, 1, "EcuStatus.boost_target_kpa"),
    _Spec("fuel_cut", "flag", _ANY, 0, "any(ActuatorCommands.fuel_cut)", flag=True),
    _Spec("ign_cut", "flag", _ANY, 0, "any(ActuatorCommands.spark_cut)", flag=True),
    _Spec("overrun_afterfire", "contagem", _SUM, 0, "nº de CombustionEvent.pop_event"),
    _Spec("roller_speed_kmh", "km/h", _L, 1, "RollerRig.vehicle_speed_kmh", min_value=0.0),
    _Spec("health_piston_pct", "%", _MN, 1, "DamageState piston:k", True),
    _Spec("health_rod_pct", "%", _MN, 1, "DamageState rod:k", True),
    _Spec("health_valves_pct", "%", _MN, 1, "DamageState valves:k", True),
    _Spec("health_head_gasket_pct", "%", _MN, 1, "DamageState head_gasket"),
    _Spec("health_bearings_pct", "%", _MN, 1, "DamageState bearings"),
    _Spec("health_turbine_pct", "%", _MN, 1, "DamageState turbo:turbine", turbo_only=True),
    _Spec("health_min_pct", "%", _MN, 1, "min(DamageState.components.health)"),
    _Spec("real_time_factor", "-", _L, 3, "EngineState.real_time_factor", nullable=True),
    # 002 RF-12 e RF-18: came variável (posição real e alvo) e sensor flex.
    _Spec("cam_intake_deg", "°", _L, 1, "SensorReadings.cam_intake_deg"),
    _Spec("cam_exhaust_deg", "°", _L, 1, "SensorReadings.cam_exhaust_deg"),
    _Spec("cam_intake_target_deg", "°", _L, 1, "ActuatorCommands.vvt_intake_target_deg"),
    _Spec("cam_exhaust_target_deg", "°", _L, 1, "ActuatorCommands.vvt_exhaust_target_deg"),
    _Spec(
        "ethanol_pct",
        "%",
        _L,
        1,
        "SensorReadings.ethanol_pct",
        nullable=True,
        min_value=0.0,
        max_value=100.0,
    ),
)


def _channel(spec: _Spec, cylinder: int | None) -> TelemetryChannel:
    kind = (
        ChannelKind.PER_CYLINDER
        if spec.per_cylinder
        else ChannelKind.FLAG
        if spec.flag
        else ChannelKind.SCALAR
    )
    return TelemetryChannel(
        name=channel_name(spec.base, cylinder),
        base=spec.base,
        cylinder=cylinder,
        unit=spec.unit,
        kind=kind,
        aggregation=spec.aggregation,
        decimals=spec.decimals,
        min_value=spec.min_value,
        max_value=spec.max_value,
        source=spec.source,
        nullable=spec.nullable,
    )


@dataclass(frozen=True, slots=True, eq=False)
class ChannelCatalog:
    """Catálogo de um motor (``n_cyl``, turbo) com índices prontos para o laço."""

    n_cyl: int
    has_turbo: bool
    channels: tuple[TelemetryChannel, ...]
    names: tuple[str, ...] = field(init=False)
    index: dict[str, int] = field(init=False)
    agg: np.ndarray = field(init=False)  # código de agregação por coluna (AGG_CODES)
    decimals: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        names = tuple(c.name for c in self.channels)
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "index", {n: i for i, n in enumerate(names)})
        object.__setattr__(
            self, "agg", np.array([AGG_CODES[c.aggregation] for c in self.channels], np.int8)
        )
        object.__setattr__(self, "decimals", np.array([c.decimals for c in self.channels]))

    def __len__(self) -> int:
        return len(self.channels)

    def __contains__(self, name: object) -> bool:
        return name in self.index

    def get(self, name: str) -> TelemetryChannel | None:
        i = self.index.get(name)
        return None if i is None else self.channels[i]

    def unknown(self, names: list[str]) -> list[str]:
        """Nomes fora do catálogo (os compostos são aceites)."""
        return [n for n in names if n not in self.index and n not in COMPOSITE_CHANNELS]


@cache
def build_catalog(n_cyl: int, has_turbo: bool) -> ChannelCatalog:
    """Catálogo expandido para ``n_cyl`` cilindros (1..8)."""
    if not 1 <= n_cyl <= 8:  # noqa: PLR2004 - limite do contrato
        raise ValueError(f"n_cyl fora de 1..8: {n_cyl}")
    channels: list[TelemetryChannel] = []
    for spec in _SPECS:
        if spec.turbo_only and not has_turbo:
            continue
        if spec.per_cylinder:
            channels.extend(_channel(spec, k) for k in range(1, n_cyl + 1))
        else:
            channels.append(_channel(spec, None))
    return ChannelCatalog(n_cyl=n_cyl, has_turbo=has_turbo, channels=tuple(channels))


def catalog_for_vehicle(vehicle: VehicleSpec) -> ChannelCatalog:
    """Catálogo do veículo do catálogo (``n_cyl`` e indução)."""
    return build_catalog(vehicle.engine.n_cyl, vehicle.induction == "turbo")
