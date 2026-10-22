"""Assistente de mapa base standalone (profiles RF-21; Apêndice E).

Função pura: a partir da ``BaseSetup`` declarada, do motor (cilindrada, cilindros, taxa de
compressão, aspiração) e das ``WizardInputs`` gera o ``CalibrationContent`` do perfil.

- Eixos: RPM de 500 a ``rev_limit_rpm`` e MAP de 20 a ``max_map_kpa + 20`` kPa (aspirado:
  até 105 kPa), ``grid`` pontos uniformes cada.
- VE (%): ``VE_pk · f_rpm · f_map`` com ``VE_pk = 85`` (sobrealimentado) ou 90 (aspirado),
  ``f_rpm = 0,80 + 0,20 · (1 − ((rpm − rpm_pk)/rpm_pk)²)`` limitado a 0,70..1,00,
  ``rpm_pk = 0,6 · rev_limit`` e ``f_map = 0,55 + 0,45 · min(map/100, 1)``. O erro face à
  VE física é proposital (o usuário afina).
- Lambda alvo: 1,00 até 70 kPa; linear até 0,90 a 100 kPa; acima, linear até 0,82 (E0,
  E27), 0,80 (Podium) ou 0,78 (E100) em ``max_map_kpa``.
- Ignição (°BTDC): ``10 + 16 · min(rpm/4000, 1) − 0,12 · max(map − 60, 0) + c_fuel
  − 1,5 · max(cr − 9, 0)``, ``c_fuel`` = 0 (E0, E27), +2 (Podium), +3 (E100); 5..35.
- ``inj_dead_time``: cópia do tempo morto declarado (tabela por tensão de bateria).
- ``direct_pulse_ms``: ``inj_base_ms = m_fuel / q_inj`` pelo speed-density do ecu-core com o
  VE base, IAT 30 °C, o lambda alvo e o combustível declarado (sem dead time).
- Duty estimado: ``PW(rpm_max, max_map) / (120000 / rpm_max) · 100``; > 85 % ⇒
  ``INJECTOR_UNDERSIZED``.
- Estratégias: limitador, failsafe e overboost da base (RF-27), malha fechada só com
  wideband, two-step/antilag/powershift/pops desligados.

Também ficam aqui o enriquecimento de partida e pós-partida (sem eles o motor não pega)
e o alvo de boost por TPS nos motores sobrealimentados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from simremap.ecu.calibration import CalibrationContent, parse_content
from simremap.ecu.compiled import EcuHardwareConfig
from simremap.ecu.contracts import (
    AntilagConfig,
    KnockControlConfig,
    OverrunConfig,
    PowershiftConfig,
    StrategyConfig,
    TwoStepConfig,
)
from simremap.ecu.strategies.fuel import speed_density_air_g
from simremap.ecu.tables import Table3D, interp1
from simremap.profiles.contracts import BaseSetup, EcuProfileId, WizardInputs
from simremap.profiles.descriptors.common import uniform
from simremap.profiles.descriptors.m1_race import CHARGE_TEMP_BLEND
from simremap.profiles.errors import profile_error
from simremap.profiles.hooks.common import FEATURE_PACKAGE_PARAM
from simremap.profiles.hooks.standalone import protection_strategies
from simremap.profiles.setup import hardware_config

if TYPE_CHECKING:
    from simremap.catalog.contracts import VehicleSpec

__all__ = [
    "DUTY_WARN_PCT",
    "WIZARD_IAT_C",
    "WizardResult",
    "base_ignition_deg",
    "base_lambda",
    "base_ve_pct",
    "derive_inj_base_ms",
    "generate_base_map",
    "switch_fuel_model_mode",
]

DUTY_WARN_PCT: Final = 85.0  # %
WIZARD_IAT_C: Final = 30.0  # °C
_DEFAULT_MODE: Final[dict[EcuProfileId, Literal["speed_density_ve", "direct_pulse_ms"]]] = {
    EcuProfileId.FT_PRO: "direct_pulse_ms",
    EcuProfileId.M1_RACE: "speed_density_ve",
    EcuProfileId.HT_ELITE: "speed_density_ve",
}
_LAMBDA_WOT: Final[dict[str, float]] = {"e0": 0.82, "e27": 0.82, "podium": 0.80, "e100": 0.78}
_IGN_FUEL: Final[dict[str, float]] = {"e0": 0.0, "e27": 0.0, "podium": 2.0, "e100": 3.0}
_ECT_AXIS: Final = [-20.0, 0.0, 20.0, 40.0, 60.0, 80.0]
_CRANK_FACTOR: Final = [2.2, 1.8, 1.5, 1.25, 1.1, 1.0]
_AFTERSTART_PCT: Final = [40.0, 30.0, 20.0, 12.0, 8.0, 5.0]
_BATTERY_REF_V: Final = 14.0  # V


@dataclass(frozen=True, slots=True)
class WizardResult:
    content: CalibrationContent
    estimated_peak_duty_pct: float  # %
    warnings: list[str] = field(default_factory=list)


def base_ve_pct(rpm: float, map_kpa: float, rev_limit_rpm: float, *, forced: bool) -> float:
    ve_pk = 85.0 if forced else 90.0
    rpm_pk = 0.6 * rev_limit_rpm
    f_rpm = 0.80 + 0.20 * (1.0 - ((rpm - rpm_pk) / rpm_pk) ** 2)
    f_rpm = min(max(f_rpm, 0.70), 1.00)
    f_map = 0.55 + 0.45 * min(map_kpa / 100.0, 1.0)
    return ve_pk * f_rpm * f_map


def base_lambda(map_kpa: float, max_map_kpa: float, fuel_id: str) -> float:
    if map_kpa <= 70.0:  # noqa: PLR2004 - Apêndice E
        return 1.00
    if map_kpa <= 100.0:  # noqa: PLR2004
        return 1.00 - 0.10 * (map_kpa - 70.0) / 30.0
    wot = _LAMBDA_WOT[fuel_id]
    if max_map_kpa <= 100.0 or map_kpa >= max_map_kpa:  # noqa: PLR2004
        return wot
    return 0.90 + (wot - 0.90) * (map_kpa - 100.0) / (max_map_kpa - 100.0)


def base_ignition_deg(rpm: float, map_kpa: float, fuel_id: str, compression_ratio: float) -> float:
    adv = (
        10.0
        + 16.0 * min(rpm / 4000.0, 1.0)
        - 0.12 * max(map_kpa - 60.0, 0.0)
        + _IGN_FUEL[fuel_id]
        - 1.5 * max(compression_ratio - 9.0, 0.0)
    )
    return min(max(adv, 5.0), 35.0)


def _pulse_ms(
    hw: EcuHardwareConfig, ve_pct: float, map_kpa: float, lam: float, *, iat_c: float
) -> float:
    """Tempo útil de injeção (ms, sem dead time) pelo speed-density do ecu-core."""
    air_g = speed_density_air_g(ve_pct, map_kpa, hw.v_cyl_m3, iat_c, iat_c, 0.0)
    fuel_g = air_g / (lam * hw.afr_stoich)
    return fuel_g / hw.q_inj_ref_g_ms


def _t3(  # noqa: PLR0917 - campos da tabela
        table_id: str, kind: str, unit: str, xs: list[float], ys: list[float],
        z: list[list[float]], yq: str = "map_kpa") -> dict[str, Any]:  # fmt: skip
    return {
        "table_id": table_id,
        "kind": kind,
        "unit": unit,
        "x": {"quantity": "rpm", "values": xs},
        "y": {"quantity": yq, "values": ys},
        "values": z,
    }


def _t2(  # noqa: PLR0917 - campos da tabela
        table_id: str, kind: str, unit: str, xq: str, xs: list[float],
        vs: list[float]) -> dict[str, Any]:  # fmt: skip
    return {
        "table_id": table_id,
        "kind": kind,
        "unit": unit,
        "x": {"quantity": xq, "values": xs},
        "values": vs,
    }


def _wizard_error(field_name: str, reason: str) -> Exception:
    return profile_error(
        "WIZARD_INPUT_INVALID",
        f"Entrada do assistente inválida: {field_name} ({reason}).",
        field=field_name,
        reason=reason,
    )


def generate_base_map(  # noqa: PLR0915 - fórmulas do Apêndice E num só passo
    profile_id: EcuProfileId,
    base: BaseSetup,
    vehicle: VehicleSpec,
    inputs: WizardInputs | None = None,
) -> WizardResult:
    """Gera o mapa base do perfil standalone (RF-21)."""
    if profile_id == EcuProfileId.OEM_STAGE:
        raise _wizard_error("profile_id", "o oem-stage não usa assistente")
    wiz = inputs or WizardInputs()
    if base.fuel is None or base.injectors is None:
        raise _wizard_error("base_setup", "bicos e combustível são obrigatórios")
    hw = hardware_config(base, vehicle)
    engine = vehicle.engine
    forced = vehicle.induction != "natural"
    rev = wiz.rev_limit_rpm if wiz.rev_limit_rpm is not None else base.protection.rev_limit_rpm
    if rev <= wiz.idle_rpm + 500.0:
        raise _wizard_error("rev_limit_rpm", "deve ficar 500 rpm acima da marcha lenta")
    max_map = wiz.max_map_kpa if forced else min(wiz.max_map_kpa, 105.0)
    map_top = max_map + 20.0 if forced else 105.0
    mode = wiz.fuel_model_mode or _DEFAULT_MODE[profile_id]
    if profile_id != EcuProfileId.FT_PRO and mode != "speed_density_ve":
        raise _wizard_error("fuel_model_mode", f"o perfil {profile_id.value} usa só VE")
    n = wiz.grid
    rpms = uniform(500.0, rev, n)
    maps = uniform(20.0, map_top, n)
    fuel_id = base.fuel.fuel_id
    cr = engine.compression_ratio

    ve = [[round(base_ve_pct(r, m, rev, forced=forced), 3) for r in rpms] for m in maps]
    lam = [[round(base_lambda(m, max_map, fuel_id), 4) for _ in rpms] for m in maps]
    ign = [[round(base_ignition_deg(r, m, fuel_id, cr), 3) for r in rpms] for m in maps]
    inj = base.injectors
    dead_14v = interp1(inj.dead_time_v, inj.dead_time_ms, _BATTERY_REF_V)
    tables: dict[str, dict[str, Any]] = {
        "ve": _t3("ve", "ve", "%", rpms, maps, ve),
        "lambda_target": _t3("lambda_target", "lambda_target", "λ", rpms, maps, lam),
        "ignition_base": _t3("ignition_base", "ignition_base", "°BTDC", rpms, maps, ign),
        "inj_dead_time": _t2(
            "inj_dead_time", "inj_dead_time", "ms", "battery_v", list(inj.dead_time_v),
            list(inj.dead_time_ms),
        ),
    }  # fmt: skip
    if mode == "direct_pulse_ms":
        pulse = [
            [
                round(min(_pulse_ms(hw, ve[i][j], maps[i], lam[i][j], iat_c=WIZARD_IAT_C), 50.0), 4)
                for j in range(n)
            ]
            for i in range(n)
        ]
        tables["inj_base_ms"] = _t3("inj_base_ms", "inj_base_ms", "ms", rpms, maps, pulse)
    # Partida e pós-partida: pulso de partida a 95 kPa e lambda 0,85 escalado pela ECT.
    crank_useful = _pulse_ms(
        hw, base_ve_pct(300.0, 95.0, rev, forced=forced), 95.0, 0.85, iat_c=20.0
    )
    tables["cranking_fuel"] = _t2(
        "cranking_fuel", "cranking_fuel", "ms", "ect_c", _ECT_AXIS,
        [round(min(crank_useful * f + dead_14v, 50.0), 4) for f in _CRANK_FACTOR],
    )  # fmt: skip
    tables["afterstart_enrich"] = _t2(
        "afterstart_enrich", "afterstart_enrich", "%", "ect_c", _ECT_AXIS, list(_AFTERSTART_PCT)
    )
    if forced:
        tps = [0.0, 50.0, 80.0, 100.0]
        targets = [100.0, 100.0, round(100.0 + 0.5 * (max_map - 100.0), 3), max_map]
        tables["boost_target"] = _t3(
            "boost_target", "boost_target", "kPa", rpms, tps,
            [[max(t, 80.0)] * n for t in targets], yq="tps_pct",
        )  # fmt: skip

    # Duty estimado no ponto de carga máxima.
    ve_pk = base_ve_pct(rev, max_map, rev, forced=forced)
    useful = _pulse_ms(
        hw, ve_pk, max_map, base_lambda(max_map, max_map, fuel_id), iat_c=WIZARD_IAT_C
    )
    duty = (useful + dead_14v) / (120000.0 / rev) * 100.0
    warnings = ["INJECTOR_UNDERSIZED"] if duty > DUTY_WARN_PCT else []

    strategies: dict[str, StrategyConfig] = protection_strategies(
        base.protection, wideband=base.sensors.wideband is not None
    )
    strategies["knock_control"] = KnockControlConfig()
    strategies["two_step"] = TwoStepConfig(
        enabled=False, target_rpm=min(4000.0, base.protection.rev_limit_rpm - 500.0)
    )
    strategies["antilag"] = AntilagConfig(enabled=False)
    strategies["powershift"] = PowershiftConfig(enabled=False)
    strategies["overrun"] = OverrunConfig(pops_enabled=False)
    params: dict[str, float | bool | str] = {}
    if profile_id == EcuProfileId.M1_RACE:
        params[FEATURE_PACKAGE_PARAM] = base.feature_package
    content = parse_content(
        {
            "vehicle_id": vehicle.vehicle_id,
            "profile_id": profile_id.value,
            "fuel_model": {
                "mode": mode,
                "charge_temp_blend": CHARGE_TEMP_BLEND
                if profile_id == EcuProfileId.M1_RACE
                else 0.0,
                "inj_duty_warn_pct": DUTY_WARN_PCT,
            },
            "tables": tables,
            "strategies": {k: v.model_dump() for k, v in strategies.items()},
            "profile_params": params,
        }
    )
    return WizardResult(content=content, estimated_peak_duty_pct=round(duty, 2), warnings=warnings)


def derive_inj_base_ms(
    ve: Table3D,
    lambda_target: Table3D | None,
    hw: EcuHardwareConfig,
    *,
    iat_c: float = WIZARD_IAT_C,
) -> dict[str, Any]:
    """``inj_base_ms`` nos eixos da VE pela equação do Apêndice E (RF-14)."""
    xs = list(ve.x.values)
    ys = list(ve.y.values)
    z = []
    for i, m in enumerate(ys):
        row = []
        for j, r in enumerate(xs):
            lam = lambda_target.lookup(r, m) if lambda_target is not None else 1.0
            row.append(round(min(_pulse_ms(hw, ve.values[i][j], m, lam, iat_c=iat_c), 50.0), 4))
        z.append(row)
    return _t3("inj_base_ms", "inj_base_ms", "ms", xs, ys, z)


def switch_fuel_model_mode(
    content: CalibrationContent,
    mode: Literal["speed_density_ve", "direct_pulse_ms"],
    hw: EcuHardwareConfig,
) -> CalibrationContent:
    """Troca o modo de injeção do ``ft-pro``; ``inj_base_ms`` é derivado da VE (RF-14)."""
    data = content.model_dump(mode="json")
    data["fuel_model"]["mode"] = mode
    if mode == "direct_pulse_ms":
        ve = content.tables.get("ve")
        if not isinstance(ve, Table3D):
            raise _wizard_error("fuel_model_mode", "a troca para ms exige a tabela ve")
        lam = content.tables.get("lambda_target")
        data["tables"]["inj_base_ms"] = derive_inj_base_ms(
            ve, lam if isinstance(lam, Table3D) else None, hw
        )
    return parse_content(data)
