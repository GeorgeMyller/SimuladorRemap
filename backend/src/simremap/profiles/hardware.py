"""Hardware real por veículo, ficha de instalação e defeitos ocultos (RF-22 a RF-26, RF-29, RF-30).

- ``load_vehicle_hardware``: ``data/hardware/<vehicle_id>.json`` (``VehicleEcuHardware``),
  carregado só do pacote; ficheiro ausente ou inválido ⇒ ``None`` e ``HARDWARE_FILE_MISSING``
  no log (EC-14): o veículo fica sem swap e o perfil OEM continua disponível.
- ``RealHardware``: verdade física vista pelo adaptador = ficheiro do veículo + bico e
  combustível do vehicle-catalog + ``HardwareOverride`` do training-scenarios.
- ``hardware_sheet``: o que o mecânico vê no carro (``HardwareSheet``); nunca contém o PMS
  real nem os overrides (Seção 12): o PMS mostrado é sempre o nominal do manual.
- Transformações de sensor do Apêndice D (funções puras): escala do MAP (S-05), curva
  NTC de IAT/ECT (S-09) e escala da wideband (S-10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from simremap.core.logging import get_logger
from simremap.profiles.contracts import (
    HardwareOverride,
    HardwareSheet,
    NtcCurve,
    TriggerWheel,
    VehicleEcuHardware,
)

if TYPE_CHECKING:
    from simremap.catalog.contracts import VehicleSpec

__all__ = [
    "KELVIN",
    "NTC_BETA_K",
    "NTC_T0_K",
    "RealHardware",
    "default_vehicle_hardware",
    "hardware_sheet",
    "load_vehicle_hardware",
    "map_read_kpa",
    "ntc_read_c",
    "real_dead_time_row",
    "real_hardware",
    "wideband_read",
]

logger = get_logger("simremap.profiles.hardware")

KELVIN: Final = 273.15
NTC_T0_K: Final = 298.15  # K, referência das curvas genéricas (Apêndice D, S-09)
NTC_BETA_K: Final[dict[str, float]] = {
    "ntc_a": 3450.0,  # K (Apêndice D)
    "ntc_b": 3950.0,  # K (Apêndice D)
    "ntc_c": 4300.0,  # K (curva genérica extra; a spec só fixa a e b)
}
_DATA_PACKAGE: Final = "simremap.profiles.data.hardware"


@cache
def load_vehicle_hardware(vehicle_id: str) -> VehicleEcuHardware | None:
    """Hardware real do veículo; ``None`` (log ``HARDWARE_FILE_MISSING``) se faltar/inválido."""
    if not vehicle_id or "/" in vehicle_id or "\\" in vehicle_id or vehicle_id.startswith("."):
        return None
    try:
        raw = resources.files(_DATA_PACKAGE).joinpath(f"{vehicle_id}.json").read_text("utf-8")
        hw = VehicleEcuHardware.model_validate(json.loads(raw))
    except (OSError, ValueError, ValidationError) as exc:
        logger.warning(
            "profiles.hardware.missing",
            code="HARDWARE_FILE_MISSING",
            vehicle_id=vehicle_id,
            reason=type(exc).__name__,
        )
        return None
    if hw.vehicle_id != vehicle_id:
        logger.warning(
            "profiles.hardware.missing",
            code="HARDWARE_FILE_MISSING",
            vehicle_id=vehicle_id,
            reason="vehicle_id_mismatch",
        )
        return None
    return hw


@dataclass(frozen=True, slots=True)
class RealHardware:
    """Verdade física usada pelo adaptador (nunca serializada para a API)."""

    trigger_wheel: TriggerWheel
    tdc_offset_deg: float  # ° (verdadeiro + deslocamento do override)
    phase_sensor_present: bool
    phase_edge_deg: float  # °
    firing_order: tuple[int, ...]
    map_sensor_kpa: tuple[float, float]  # kPa (mín, máx)
    iat_curve: NtcCurve
    ect_curve: NtcCurve
    wideband: tuple[float, float]  # λ a 0 V e a 5 V
    injector_flow_cc_min: float  # cc/min do bico instalado (catálogo ou override)
    catalog_injector_flow_cc_min: float  # cc/min do InjectorSpec usado pela física
    tank_fuel_id: str


def real_hardware(
    hw: VehicleEcuHardware, vehicle: VehicleSpec, override: HardwareOverride | None = None
) -> RealHardware:
    """Combina o ficheiro de hardware, o catálogo e o defeito oculto (RF-29)."""
    ov = override or HardwareOverride()
    catalog_flow = vehicle.injectors.flow_cc_min * vehicle.injectors.count_per_cyl
    return RealHardware(
        trigger_wheel=ov.trigger_wheel or hw.trigger_wheel,
        tdc_offset_deg=hw.tdc_offset_true_deg + ov.tdc_offset_shift_deg,
        phase_sensor_present=hw.phase_sensor_present,
        phase_edge_deg=hw.phase_edge_true_deg,
        firing_order=tuple(hw.firing_order),
        map_sensor_kpa=ov.map_sensor_kpa or hw.map_sensor_kpa,
        iat_curve=hw.iat_curve,
        ect_curve=hw.ect_curve,
        wideband=hw.wideband_true,
        injector_flow_cc_min=ov.injector_flow_cc_min or catalog_flow,
        catalog_injector_flow_cc_min=catalog_flow,
        tank_fuel_id=ov.tank_fuel_id or vehicle.stock_fuel_id,
    )


def hardware_sheet(hw: VehicleEcuHardware, vehicle: VehicleSpec) -> HardwareSheet:
    """Ficha de instalação visível (RF-30): etiquetas nominais, sem PMS real nem overrides."""
    inj = vehicle.injectors
    return HardwareSheet(
        trigger_wheel=hw.trigger_wheel,
        phase_sensor_present=hw.phase_sensor_present,
        firing_order=list(hw.firing_order),
        injector_label_cc_min=inj.flow_cc_min * inj.count_per_cyl,
        tank_fuel_id=vehicle.stock_fuel_id,
        map_sensor_label_kpa=hw.map_sensor_kpa,
        tdc_offset_nominal_deg=hw.tdc_offset_nominal_deg,
        n_cyl=vehicle.engine.n_cyl,
        displacement_cc=vehicle.engine.displacement_cc,
    )


# --------------------------------------------------------------------------- Apêndice D


def map_read_kpa(p_kpa: float, real: tuple[float, float], declared: tuple[float, float]) -> float:
    """MAP lido pela ECU (S-05, EC-12).

    ``map_read = min_cfg + (p − min_real) · (max_cfg − min_cfg) / (max_real − min_real)``,
    saturado na faixa declarada (0,5–4,5 V do sensor). Escalas iguais devolvem ``p``
    inalterado dentro da faixa.
    """
    lo_r, hi_r = real
    lo_c, hi_c = declared
    if p_kpa <= lo_r:
        return lo_c
    if p_kpa >= hi_r:
        return hi_c
    if real == declared:
        return p_kpa
    return lo_c + (p_kpa - lo_r) * (hi_c - lo_c) / (hi_r - lo_r)


def ntc_read_c(t_c: float, real: str, declared: str) -> float:
    """Temperatura lida com a curva NTC declarada sobre o termistor real (S-09).

    ``R = R0 · exp(β_real · (1/T − 1/T0))`` e ``T_read = 1 / (1/T0 + ln(R/R0) / β_cfg)``.
    """
    if real == declared:
        return t_c
    t_k = t_c + KELVIN
    ln_r_over_r0 = NTC_BETA_K[real] * (1.0 / t_k - 1.0 / NTC_T0_K)  # ln(R/R0) do termistor real
    return 1.0 / (1.0 / NTC_T0_K + ln_r_over_r0 / NTC_BETA_K[declared]) - KELVIN


def wideband_read(lam: float, real: tuple[float, float], declared: tuple[float, float]) -> float:
    """Lambda lido (S-10): ``λ0_cfg + (λ − λ0_real) · (λ5_cfg − λ0_cfg) / (λ5_real − λ0_real)``."""
    if real == declared:
        return lam
    l0r, l5r = real
    l0c, l5c = declared
    return l0c + (lam - l0r) * (l5c - l0c) / (l5r - l0r)


def default_vehicle_hardware(vehicle: VehicleSpec) -> VehicleEcuHardware:
    """Hardware mínimo derivado do catálogo quando falta o ficheiro (EC-14: sem swap)."""
    engine = vehicle.engine
    return VehicleEcuHardware(
        vehicle_id=vehicle.vehicle_id,
        trigger_wheel=engine.crank_trigger,
        tdc_offset_true_deg=90.0,
        tdc_offset_nominal_deg=90.0,
        phase_sensor_present=engine.cam_sync != "none",
        phase_edge_true_deg=0.0,
        firing_order=list(engine.firing_order),
        map_sensor_kpa=(20.0, 400.0),
        swap_supported=False,
    )


def real_dead_time_row(vehicle: VehicleSpec) -> tuple[list[float], list[float]]:
    """Tempo morto real do bico (linha de ΔP mais próxima da referência do catálogo)."""
    grid = vehicle.injectors.dead_time_ms
    ys = grid.y_values
    row = min(range(len(ys)), key=lambda i: abs(ys[i] - vehicle.injectors.dp_ref_kpa))
    return list(grid.x_values), list(grid.z_values[row])
