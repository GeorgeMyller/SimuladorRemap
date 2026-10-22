"""Contexto partilhado do tick entre as estratégias (ecu-core Apêndice D).

``TickContext`` é preenchido pelo ``EcuRuntime`` no passo 1 (sensores validados) e
atualizado ao longo do pipeline; as estratégias leem-no e acrescentam ``EcuEvent`` a
``events``. Um único objeto por runtime, reutilizado em todos os ticks.
"""

from __future__ import annotations

from math import nan

from simremap.ecu.compiled import N_INPUTS
from simremap.ecu.contracts import EcuEvent, EcuEventKind

__all__ = ["TickContext"]


class TickContext:
    __slots__ = (
        "adv_ref",
        "antilag_switch",
        "baro_kpa",
        "battery_v",
        "boost_target_kpa",
        "clutch_pressed",
        "cycle_counter",
        "dt",
        "ect_c",
        "egt_c",
        "events",
        "fuel_cut_prev",
        "fuel_pressure_kpa",
        "gear",
        "iat_c",
        "inputs",
        "knock_intensity",
        "lambda_measured",
        "lambda_target_base",
        "lambda_target_prev",
        "lambda_valid",
        "launch_switch",
        "map_kpa",
        "n_cyl",
        "oil_pressure_kpa",
        "pedal_pct",
        "rpm",
        "sensor_fault",
        "shift_request",
        "t",
        "tick",
        "tps_pct",
        "tps_rate_pct_s",
        "vehicle_speed_kmh",
    )

    def __init__(self, n_cyl: int) -> None:
        self.n_cyl = n_cyl
        self.inputs: list[float] = [0.0] * N_INPUTS
        self.events: list[EcuEvent] = []
        self.knock_intensity: list[float] = [0.0] * n_cyl
        self.t = 0.0
        self.dt = 0.001
        self.tick = 0
        self.rpm = 0.0
        self.map_kpa = 101.325
        self.baro_kpa = 101.325
        self.tps_pct = 0.0
        self.tps_rate_pct_s = 0.0
        self.pedal_pct = 0.0
        self.ect_c = 20.0
        self.iat_c = 20.0
        self.egt_c = 20.0
        self.battery_v = 14.0
        self.oil_pressure_kpa = 0.0
        self.fuel_pressure_kpa = 300.0
        self.lambda_measured = nan
        self.lambda_valid = False
        self.gear = 0
        self.vehicle_speed_kmh = 0.0
        self.clutch_pressed = False
        self.launch_switch = False
        self.shift_request = False
        self.antilag_switch = False
        self.sensor_fault = False
        self.cycle_counter = 0
        self.lambda_target_base = 1.0
        self.lambda_target_prev = 1.0
        self.boost_target_kpa = 101.325
        self.adv_ref = 0.0
        self.fuel_cut_prev = False

    def emit(
        self,
        kind: EcuEventKind,
        *,
        cylinder: int | None = None,
        value: float | None = None,
        detail: str = "",
    ) -> None:
        """Acrescenta um ``EcuEvent`` do tick (fora do caminho comum: só em transições)."""
        self.events.append(
            EcuEvent.model_construct(
                t_sim_s=self.t, kind=kind, cylinder=cylinder, value=value, detail=detail[:200]
            )
        )
