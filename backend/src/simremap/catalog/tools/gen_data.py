"""Autoria determinística dos dados do catálogo (Apêndices A.1 a A.7 da spec vehicle-catalog).

Gera, a partir das tabelas da spec, os arquivos de ``catalog/data/``:
``fuels/<fuel_id>.json``, ``vehicles/<id>/vehicle.json`` (``validated`` quando a afinação
física passa o teste de acurácia, senão ``draft``),
``vehicles/<id>/reference-curves/stock-<fuel>.json`` (``Reference Benchmark Baseline v1``,
passo 250 rpm, âncoras a 500 rpm), ``vehicles/<id>/calibrations/oem-stage.json`` (schema
``Calibration`` do ecu-core, ``metadata.source = oem_stock``, lógica OEM por torque) e o
mapa base ``ft-pro`` do ``classic-20t-swap``; no fim regrava o ``manifest.json``.

Uso::

    uv run python -m simremap.catalog.tools.gen_data --force

O gerador é a fonte de verdade dos dados (``test_regeneration_is_byte_identical``): a
afinação contra o ``Reference Benchmark Baseline v1`` (T267, T403-T405) vive nas fontes
``VEHICLES`` (turbo/supercharger, VE, Wiebe, Chen-Flynn e a tabela ``wot`` de avanço e MAP
alvo por RPM) e chega ao ``vehicle.json`` e à calibração ``oem-stage`` por regeneração.
O gerador recusa sobrescrever sem ``--force``.
"""

from __future__ import annotations

import argparse
import math
import sys
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from simremap.catalog.canonical import canonical_sha256, sha256_bytes
from simremap.catalog.contracts import KW_PER_HP, Grid2D
from simremap.catalog.drivetrain import crank_power_kw
from simremap.catalog.grids import interp2d, interp_linear
from simremap.catalog.tools.gen_ve import ve_grid
from simremap.catalog.tools.jsonfmt import dumps_pretty, write_json
from simremap.catalog.tools.rehash import DEFAULT_CATALOG_DIR, rehash
from simremap.ecu.contracts import (
    AntilagConfig,
    BoostControlConfig,
    ClosedLoopConfig,
    FailsafeConfig,
    KnockControlConfig,
    OverrunConfig,
    PowershiftConfig,
    RevLimiterConfig,
    TwoStepConfig,
)

__all__ = [
    "CALIBRATION_CREATED_AT",
    "FUELS",
    "VEHICLES",
    "build_all",
    "calibration_content_hash",
    "main",
    "oem_checksum",
]

CALIBRATION_CREATED_AT: Final = "2026-10-18T00:00:00Z"
CATALOG_VERSION: Final = "1.1.0"  # 1.1.0: afinação física e veículos validated (T268, T406)
VALIDATED_ON: Final = "2026-10-18"  # data da validação contra o benchmark (RF-29)
BARO_KPA: Final = 101.325
R_AIR: Final = 287.05
T_CHARGE_K: Final = 313.15  # carga após o intercooler (40 °C), modelo da ECU
T_REF_K: Final = 273.15
KNOCK_SENSOR_BAR_TO_INDEX: Final = 1.5 / 4.95  # V/bar ÷ faixa útil de 0,05–5,0 V
LAMBDA_BLEND_LOW: Final = 60.0  # kPa: início do enriquecimento de carga no lambda_target OEM
PUBLIC_SPEC_SOURCE: Final = "ficha técnica pública da arquitetura de inspiração"
HEYWOOD: Final = "Heywood, J. B. Internal Combustion Engine Fundamentals (1988)"
INTERNAL_ESTIMATE: Final = "Reference Benchmark Baseline v1 (estimativa interna)"
CHEN_FLYNN_B: Final = 0.09  # bar·s/m, coeficiente padrão (literatura)
TUNED_NOTE: Final = (
    "afinado na física headless contra o Reference Benchmark Baseline v1 "
    "(desvio < 5 % em torque, potência, lambda e EGT; T267, T403-T405)"
)


def _r(value: float, nd: int = 6) -> float:
    """Arredonda e devolve sempre ``float`` (o hash da calibração usa 6 casas)."""
    return float(round(value, nd))


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _linspace(start: float, stop: float, n: int, nd: int = 3) -> list[float]:
    step = (stop - start) / (n - 1)
    return [_r(start + i * step, nd) for i in range(n)]


# =========================================================================== combustíveis

GASOLINE_LAMINAR: Final = (0.305, -0.549, 1.21)  # Metghalchi-Keck (literature)
ETHANOL_LAMINAR: Final = (0.465, -1.0, 1.10)  # estimativa


def _laminar(ethanol: float) -> tuple[float, float, float]:
    return tuple(  # type: ignore[return-value]
        _r(g + ethanol * (e - g), 5) for g, e in zip(GASOLINE_LAMINAR, ETHANOL_LAMINAR, strict=True)
    )


def _fuel(
    fuel_id: str,
    name: str,
    values: tuple[float, float, float, float, float, float, float, float, float],
    estimated: Sequence[str],
) -> dict[str, Any]:
    afr, lhv, ron, mon, knock_on, h_fg, rho, ethanol, preign = values
    bm, bphi, phim = _laminar(ethanol)
    doc = {"kind": "literature", "note": "Apêndice A.5 da spec vehicle-catalog", "source": HEYWOOD}
    prov: dict[str, Any] = {
        f"/{name_}": dict(doc)
        for name_ in ("afr_stoich", "lhv_mj_kg", "h_fg_kj_kg", "density_kg_m3")
    }
    prov["/ethanol_mass_fraction"] = {
        "kind": "literature",
        "note": "fração mássica de etanol",
        "source": "especificação brasileira de combustíveis",
    }
    for name_ in ("ron", "mon", "knock_on", "preignition_surface_temp_c", *estimated):
        prov[f"/{name_}"] = {"kind": "estimate", "note": "estimativa a validar"}
    if ethanol == 0.0:
        lam_doc = {
            "kind": "literature",
            "note": "Metghalchi-Keck, gasolina",
            "source": "Metghalchi, M.; Keck, J. C. Combustion and Flame 48 (1982)",
        }
    else:
        lam_doc = {"kind": "estimate", "note": "interpolação linear pela fração mássica de etanol"}
    for name_ in ("laminar_bm_m_s", "laminar_bphi_m_s", "laminar_phi_m"):
        prov[f"/{name_}"] = dict(lam_doc)
    return {
        "fuel_id": fuel_id,
        "display_name": name,
        "afr_stoich": afr,
        "lhv_mj_kg": lhv,
        "ron": ron,
        "mon": mon,
        "knock_on": knock_on,
        "h_fg_kj_kg": h_fg,
        "density_kg_m3": rho,
        "ethanol_mass_fraction": ethanol,
        "laminar_bm_m_s": bm,
        "laminar_bphi_m_s": bphi,
        "laminar_phi_m": phim,
        "preignition_surface_temp_c": preign,
        "provenance": dict(sorted(prov.items())),
    }


FUELS: Final[dict[str, dict[str, Any]]] = {
    "e27": _fuel("e27", "Gasolina comum E27",
                 (13.2, 38.7, 94.0, 82.0, 94.0, 512.0, 745.0, 0.28, 880.0), ()),
    "e100": _fuel("e100", "Etanol hidratado E100",
                  (9.0, 26.8, 109.0, 90.0, 106.0, 920.0, 789.0, 1.0, 830.0), ()),
    "podium": _fuel("podium", "Gasolina de competição",
                    (14.4, 42.9, 102.0, 88.0, 102.0, 340.0, 755.0, 0.0, 920.0), ()),
    "e0": _fuel("e0", "Gasolina pura E0",
                (14.7, 43.4, 95.0, 85.0, 95.0, 350.0, 740.0, 0.0, 900.0), ()),
}  # fmt: skip
FUELS["e0"]["provenance"].update(
    {
        f"/{n}": {"kind": "literature", "note": "Apêndice A.5", "source": HEYWOOD}
        for n in ("ron", "mon", "knock_on")
    }
)


# =========================================================================== veículos


@dataclass(frozen=True)
class Turbo:
    housing: str
    rotor_inertia: float
    bearing_k: float
    turbine_area: float
    wastegate_kind: str
    wastegate_area: float
    spring_kpa: float
    pr_design: float
    n_design: float
    n_max: float
    m_choke: float
    eta_max: float
    m_pk: float
    m_range: float
    compressor_ar: float | None = None
    turbine_ar: float | None = None
    full_open_delta_kpa: float = 40.0
    k1: float = 0.6
    turbine_eta: tuple[tuple[float, ...], tuple[float, ...]] = (
        (1.0, 1.5, 2.0, 2.5, 3.0, 3.5),
        (0.50, 0.65, 0.70, 0.70, 0.67, 0.63),
    )


@dataclass(frozen=True)
class Supercharger:
    displacement_l: float
    pulley_ratio: float
    k_leak: float
    adiabatic_eta: tuple[tuple[float, ...], tuple[float, ...]]
    mech_eta: float
    n_ref: float = 10_000.0
    max_rotor_rpm: float = 18_000.0


@dataclass(frozen=True)
class Vvt:
    intake_max: float
    exhaust_max: float | None


@dataclass(frozen=True)
class VehicleSource:
    """Valores das tabelas A.1 a A.4 de um veículo."""

    vehicle_id: str
    display_name: str
    architecture_note: str
    body: str
    induction: str
    architecture: str
    n_cyl: int
    v_angle: float | None
    bore: float
    stroke: float
    rod: float
    cr: float
    displacement: float
    valvetrain: str
    valves: int
    firing_order: list[int]
    vvt: Vvt | None
    ivc: float
    evo: float
    injection: str
    trigger: str
    cam_sync: str
    throttle_mm: float
    throttle_loc: str
    v_intake: float
    v_boost: float | None
    v_exhaust: float
    ic_kind: str
    ic_eff: float
    ic_k: float
    recip_g: float
    wiebe_deg: float
    stock_fuel: str
    fuels: list[str]
    drive: str
    gears: list[float]
    final_drive: float
    tire_m: float
    eta: float
    inertia: float
    turbo: Turbo | None
    injector: tuple[float, float, float, float, str, float]  # vazão, dp_ref, rail mín/máx, ref, t14
    limits: dict[str, float | None]
    map_target_kpa: float  # teto da pressão alvo de série (kPa)
    curve_fuel: str
    anchors: list[tuple[float, float, float, float]]  # rpm, torque, lambda, egt
    rated: dict[str, Any]
    prd: dict[str, str]  # ponteiro → nota
    estimates: dict[str, str] = field(default_factory=dict)  # ponteiro → nota (kind estimate)
    extra_profiles: tuple[str, ...] = ()
    # Afinação contra o Reference Benchmark Baseline v1 (T267, T403-T405): plena carga por
    # RPM (rpm, avanço ° BTDC, MAP alvo kPa) nos pontos de 250 rpm da curva de série.
    wot: tuple[tuple[float, float, float], ...] = ()
    friction_b: float = 0.09  # Chen-Flynn b (bar·s/m)
    validated: bool = False  # True quando o teste de acurácia passa (RN-05)
    supercharger: Supercharger | None = None
    # Correção da VE do modelo da ECU (oem-stage) em carga com pressão: razão ar aprisionado
    # na física / ar do speed-density da ECU medida em regime permanente a plena carga
    # (rpm, k). Aplicada com peso clip((MAP − 100)/100, 0, 1): 0 em vácuo (malha fechada
    # λ 1), total a partir de 200 kPa. Sem ela o λ real a plena carga ficava 2–11 % pobre.
    ve_ecu_wot_corr: tuple[tuple[float, float], ...] = ()
    # Retardo do avanço base (° por kPa) nas células de carga acima da plena carga de série
    # (só alcançadas com a pressão alvo acima da de série, p. ex. num remap); abaixo dela o
    # avanço sobe 0,08 °/kPa em todos os veículos.
    ign_slope_above_wot: float = 0.08


def _limits(  # noqa: PLR0917
    rod: float,
    load_kn: float,
    pcyl: float,
    egt: float,
    rev: float,
    mx: float,
    vf: float,
    turbo_rpm: float | None,
    piston: float,
) -> dict[str, float | None]:
    return {
        "rod_torque_limit_nm": rod, "max_rod_load_kn": load_kn,
        "max_cylinder_pressure_bar": pcyl, "egt_max_c": egt, "max_rpm": mx,
        "rev_limit_rpm": rev, "valve_float_rpm": vf, "turbo_max_rpm": turbo_rpm,
        "max_piston_temp_c": piston,
    }  # fmt: skip


VEHICLES: Final[tuple[VehicleSource, ...]] = (
    VehicleSource(
        vehicle_id="hatch-20t-gdi",
        display_name="Hatch 2.0 turbo GDI",
        architecture_note="Inspirado em arquitetura 2.0 turbo GDI de 4 cilindros",
        body="hatch",
        induction="turbo",
        architecture="inline",
        n_cyl=4,
        v_angle=None,
        bore=82.5,
        stroke=92.8,
        rod=144.0,
        cr=9.6,
        displacement=1984.0,
        valvetrain="dohc",
        valves=4,
        firing_order=[1, 3, 4, 2],
        vvt=Vvt(50.0, 30.0),
        ivc=40.0,
        evo=45.0,
        injection="gdi",
        trigger="60-2",
        cam_sync="1x",
        throttle_mm=56.0,
        throttle_loc="post_compressor",
        v_intake=3.0,
        v_boost=4.5,
        v_exhaust=0.8,
        ic_kind="air_to_air",
        ic_eff=0.82,  # gain-calibration: intercooler frontal com o ventilador da bancada
        ic_k=200.0,
        recip_g=600.0,
        wiebe_deg=55.0,
        stock_fuel="e27",
        fuels=["e27", "podium", "e0"],
        drive="fwd",
        gears=[3.46, 2.05, 1.30, 0.92, 0.74, 0.62],
        final_drive=4.12,
        tire_m=0.316,
        eta=0.85,
        inertia=2.4,
        # Turbo da classe IS20 (gain-calibration): turbina de 3,2 cm² efetivos (A/R maior que
        # o K03), η_t de pico 0,79 e compressor com a ilha de η 0,77 em 0,24 kg/s; as linhas
        # de velocidade mantêm a forma de PR_0(N) do mapa original (2,9 a 200 000 rpm), com
        # o choke de 0,488 kg/s a 250 000 rpm (≈ 575 m/s na ponta de uma roda de ~44 mm).
        # Stage 1 (~1,6 bar) roda a ~225 000 rpm e Stage 2 (~1,9 bar) perto da rotação máxima.
        turbo=Turbo(
            "single_scroll",
            2.0e-5,
            4.5e-7,
            3.2,
            "internal",
            6.0,
            50.0,
            2.9,
            200_000.0,
            250_000.0,
            0.488,
            0.77,
            0.24,
            0.26,
            full_open_delta_kpa=8.0,
            k1=0.5,
            turbine_eta=((1.0, 1.5, 2.0, 3.0), (0.66, 0.76, 0.79, 0.77)),
        ),
        injector=(870.0, 10_000.0, 5000.0, 20_000.0, "cylinder", 0.35),
        limits=_limits(420.0, 52.0, 120.0, 950.0, 6500.0, 6800.0, 7200.0, 250_000.0, 330.0),
        map_target_kpa=235.0,
        curve_fuel="e27",
        anchors=[
            (2000, 350.0, 0.95, 720),
            (2500, 350.0, 0.95, 760),
            (3000, 350.0, 0.95, 800),
            (3500, 350.0, 0.93, 840),
            (4000, 350.0, 0.90, 870),
            (4500, 350.0, 0.88, 890),
            (5000, 345.0, 0.85, 905),
            (5500, 331.0, 0.83, 915),
            (6000, 307.3, 0.82, 920),
            (6500, 276.0, 0.82, 925),
        ],
        rated={
            "peak_power_whp": 220.0,
            "peak_power_rpm": 6000.0,
            "peak_torque_nm": 350.0,
            "peak_torque_rpm_from": 2000.0,
            "peak_torque_rpm_to": 4500.0,
            "power_ceiling_whp": 300.0,
            "power_range_whp": None,
        },
        prd={
            "/engine/displacement_cc": "PRD seção 7, item 1: 1984 cc",
            "/engine/n_cyl": "PRD seção 7, item 1: 4 cilindros",
            "/engine/compression_ratio": "PRD seção 7, item 1: taxa 9,6:1",
            "/rated/peak_power_whp": "PRD seção 7, item 1: 220 whp de série",
            "/rated/peak_torque_nm": "PRD seção 7, item 1: 350 N·m de série",
            "/mechanical_limits/rod_torque_limit_nm": "PRD: limite da biela de série ~420 N·m",
            "/mechanical_limits/egt_max_c": "PRD seção 7, item 1: EGT 950 °C",
            "/induction": "PRD seção 7, item 1: turbo",
            "/stock_profile_id": "PRD seção 7, item 1: ECU OEM de série",
        },
        estimates={"/rated/power_ceiling_whp": "teto estimado pelo limite da biela"},
        ve_ecu_wot_corr=(
            (1500.0, 1.0577),
            (2000.0, 1.0626),
            (2500.0, 1.068),
            (3000.0, 1.0625),
            (3500.0, 1.0568),
            (4000.0, 1.0514),
            (4500.0, 1.0466),
            (5000.0, 1.0415),
            (5500.0, 1.0363),
            (6000.0, 1.033),
        ),
        # 2000–3500 rpm limitados por detonação e pressão de pico (prática OEM): avanço
        # 1–6° abaixo do ótimo e torque até 3,6 % abaixo da âncora; p_max ≈ 93 bar e força
        # na biela ≈ 48 kN em regime (limite 52 kN, folga para o ciclo a ciclo).
        # Acima de 3500 rpm (gain-calibration) o avanço de série fica 6° atrás do antigo a
        # partir de 5000 rpm (margem de knock e EGT pré-turbina da série) e a pressão alvo cai
        # de 222 kPa (5000 rpm) para 198 kPa (6500 rpm): é a ECU que limita a série em alta
        # (proteção do turbo), não a VE nem o turbo — o remap ganha ao manter a pressão.
        wot=(
            (2000, 12.6, 205.6),
            (2250, 12.6, 203.8),
            (2500, 13.6, 202.6),
            (2750, 15.4, 200.6),
            (3000, 16.4, 200.2),
            (3250, 17.2, 201.2),
            (3500, 17.6, 202.6),
            (3750, 18.0, 206.0),
            (4000, 17.7, 210.4),
            (4250, 18.2, 213.6),
            (4500, 18.5, 216.9),
            (4750, 18.8, 220.1),
            (5000, 19.1, 221.8),
            (5250, 20.8, 220.8),
            (5500, 22.3, 219.1),
            (5750, 24.3, 214.7),
            (6000, 25.8, 210.2),
            (6250, 27.3, 203.5),
            (6500, 27.6, 198.2),
        ),
        # Mapa base acima da plena carga de série: −0,03 °/kPa (só um remap lá chega); o
        # knock control da ECU retira o resto quando a detonação aparece.
        ign_slope_above_wot=0.03,
        friction_b=0.07,
        validated=True,
    ),
    VehicleSource(
        vehicle_id="coupe-30t-i6",
        display_name="Coupé 3.0 turbo 6 em linha",
        architecture_note="Inspirado em arquitetura 3.0 turbo de 6 cilindros em linha",
        body="coupe",
        induction="turbo",
        architecture="inline",
        n_cyl=6,
        v_angle=None,
        bore=82.0,
        stroke=94.6,
        rod=144.4,
        cr=10.2,
        displacement=2998.0,
        valvetrain="dohc",
        valves=4,
        firing_order=[1, 5, 3, 6, 2, 4],
        vvt=Vvt(70.0, 55.0),
        ivc=45.0,
        evo=45.0,
        injection="gdi",
        trigger="60-2",
        cam_sync="1x",
        throttle_mm=68.0,
        throttle_loc="post_compressor",
        v_intake=4.0,
        v_boost=3.0,
        v_exhaust=1.2,
        ic_kind="air_to_water",
        ic_eff=0.80,
        ic_k=100.0,
        recip_g=610.0,
        wiebe_deg=55.0,
        stock_fuel="e27",
        fuels=["e27", "podium", "e0"],
        drive="rwd",
        gears=[5.00, 3.20, 2.14, 1.72, 1.31, 1.00, 0.82, 0.64],
        final_drive=3.15,
        tire_m=0.333,
        eta=0.85,
        inertia=3.2,
        turbo=Turbo(
            "twin_scroll",
            3.5e-5,
            5.5e-7,
            4.5,
            "internal",
            16.0,
            60.0,
            3.25,
            170_000.0,
            190_000.0,
            0.66,
            0.76,
            0.22,
            0.35,
            full_open_delta_kpa=8.0,
            k1=0.5,
            turbine_eta=((1.0, 1.5, 2.0, 3.0), (0.62, 0.72, 0.75, 0.72)),
        ),
        injector=(1100.0, 10_000.0, 5000.0, 20_000.0, "cylinder", 0.35),
        limits=_limits(1000.0, 95.0, 160.0, 980.0, 7000.0, 7200.0, 7600.0, 180_000.0, 360.0),
        map_target_kpa=250.0,
        curve_fuel="e27",
        anchors=[
            (1500, 430.0, 0.98, 700),
            (2000, 500.0, 0.95, 760),
            (3000, 500.0, 0.90, 820),
            (4000, 500.0, 0.86, 870),
            (5000, 500.0, 0.82, 910),
            (5500, 495.0, 0.80, 930),
            (6000, 474.5, 0.80, 940),
            (6500, 425.0, 0.80, 945),
            (7000, 380.0, 0.80, 950),
        ],
        rated={
            "peak_power_whp": 340.0,
            "peak_power_rpm": 6000.0,
            "peak_torque_nm": 500.0,
            "peak_torque_rpm_from": 2000.0,
            "peak_torque_rpm_to": 5000.0,
            "power_ceiling_whp": 750.0,
            "power_range_whp": None,
        },
        prd={
            "/engine/displacement_cc": "PRD seção 7, item 2: 2998 cc",
            "/engine/n_cyl": "PRD seção 7, item 2: 6 cilindros",
            "/engine/architecture": "PRD seção 7, item 2: 6 em linha",
            "/engine/compression_ratio": "PRD seção 7, item 2: variante 10,2:1 (OQ-01)",
            "/rated/peak_power_whp": "PRD seção 7, item 2: 340 whp de série",
            "/rated/power_ceiling_whp": "PRD seção 7, item 2: internos forjados até 750 whp",
            "/mechanical_limits/egt_max_c": "PRD seção 7, item 2: EGT 980 °C",
            "/induction": "PRD seção 7, item 2: turbo",
            "/turbo/housing": "PRD seção 7, item 2: um único turbo",
        },
        estimates={"/mechanical_limits/rod_torque_limit_nm": "internos forjados (OQ-06)"},
        ve_ecu_wot_corr=(
            (1500.0, 1.0617),
            (2000.0, 1.0751),
            (2500.0, 1.0708),
            (3000.0, 1.0662),
            (3500.0, 1.0552),
            (4000.0, 1.0497),
            (4500.0, 1.0427),
            (5000.0, 1.0383),
            (5500.0, 1.0294),
            (6000.0, 1.0217),
            (6500.0, 1.0197),
        ),
        wot=(
            (1500, 5.0, 185.0),
            (1750, 5.5, 194.0),
            (2000, 6.1, 203.7),
            (2250, 7.3, 203.1),
            (2500, 8.4, 203.1),
            (2750, 9.0, 203.6),
            (3000, 9.5, 204.9),
            (3250, 10.0, 206.6),
            (3500, 10.8, 208.8),
            (3750, 11.4, 211.6),
            (4000, 12.2, 215.0),
            (4250, 13.8, 219.3),
            (4500, 14.8, 223.6),
            (4750, 16.4, 228.4),
            (5000, 17.2, 233.1),
            (5250, 18.9, 238.5),
            (5500, 21.0, 243.4),
            (5750, 23.4, 245.5),
            (6000, 25.7, 244.9),
            (6250, 27.1, 241.2),
            (6500, 27.7, 235.9),
            (6750, 29.2, 231.5),
            (7000, 30.4, 229.3),
        ),
        friction_b=0.07,
        validated=True,
    ),
    VehicleSource(
        vehicle_id="classic-20t-swap",
        display_name="Clássico 2.0 turbo de swap",
        architecture_note="Inspirado em arquitetura 2.0 8v de 4 cilindros turbo forjado",
        body="sedan",
        induction="turbo",
        architecture="inline",
        n_cyl=4,
        v_angle=None,
        bore=82.5,
        stroke=92.8,
        rod=144.0,
        cr=8.5,
        displacement=1984.0,
        valvetrain="sohc",
        valves=2,
        firing_order=[1, 3, 4, 2],
        vvt=None,
        ivc=38.0,
        evo=40.0,
        injection="pfi",
        trigger="60-2",
        cam_sync="1x",
        throttle_mm=60.0,
        throttle_loc="post_compressor",
        v_intake=3.5,
        v_boost=6.0,
        v_exhaust=1.5,
        ic_kind="air_to_air",
        ic_eff=0.72,
        ic_k=60.0,
        recip_g=640.0,
        wiebe_deg=52.0,
        stock_fuel="e100",
        fuels=["e100", "e27", "podium"],
        drive="fwd",
        gears=[3.45, 1.94, 1.29, 0.97, 0.80],
        final_drive=3.89,
        tire_m=0.300,
        eta=0.88,
        inertia=2.0,
        turbo=Turbo(
            "single_scroll",
            4.5e-5,
            6.5e-7,
            4.2,
            "external",
            11.3,
            90.0,
            3.9,
            140_000.0,
            155_000.0,
            0.55,
            0.75,
            0.28,
            0.32,
            compressor_ar=0.50,
            turbine_ar=0.63,
            full_open_delta_kpa=8.0,
            k1=0.5,
            turbine_eta=((1.0, 1.5, 2.0, 3.0), (0.55, 0.68, 0.72, 0.70)),
        ),
        injector=(2000.0, 300.0, 300.0, 300.0, "manifold", 1.00),
        limits=_limits(720.0, 70.0, 140.0, 950.0, 7500.0, 7800.0, 8200.0, 150_000.0, 350.0),
        map_target_kpa=300.0,
        curve_fuel="e100",
        anchors=[
            (3000, 330.0, 0.82, 680),
            (3500, 380.0, 0.81, 710),
            (4000, 430.0, 0.80, 740),
            (4500, 440.0, 0.79, 765),
            (5000, 450.0, 0.78, 790),
            (5500, 435.0, 0.78, 805),
            (6000, 420.0, 0.78, 820),
            (6500, 397.0, 0.78, 835),
            (7000, 355.0, 0.78, 845),
            (7500, 320.0, 0.78, 850),
        ],
        rated={
            "peak_power_whp": None,
            "peak_power_rpm": None,
            "peak_torque_nm": 450.0,
            "peak_torque_rpm_from": 5000.0,
            "peak_torque_rpm_to": 5000.0,
            "power_ceiling_whp": 600.0,
            "power_range_whp": [300.0, 600.0],
        },
        prd={
            "/engine/displacement_cc": "PRD seção 7, item 3: 1984 cc",
            "/engine/n_cyl": "PRD seção 7, item 3: 4 cilindros",
            "/engine/compression_ratio": "PRD seção 7, item 3: taxa 8,5:1",
            "/turbo/compressor_ar": "PRD seção 7, item 3: turbina .50/.63",
            "/turbo/turbine_ar": "PRD seção 7, item 3: turbina .50/.63",
            "/stock_fuel_id": "PRD seção 7, item 3: etanol E100",
            "/rated/power_range_whp": "PRD seção 7, item 3: 300 a 600 whp",
            "/rated/power_ceiling_whp": "PRD seção 7, item 3: até 600 whp",
        },
        estimates={
            "/mechanical_limits/egt_max_c": "a confirmar (OQ-07)",
            "/stock_profile_id": "perfil de série conservador (OQ-03)",
        },
        extra_profiles=("ft-pro",),
        wot=(
            (3000, 17.9, 222.5),
            (3250, 18.3, 231.7),
            (3500, 18.4, 244.6),
            (3750, 18.9, 259.7),
            (4000, 19.4, 275.1),
            (4250, 20.3, 279.2),
            (4500, 21.0, 279.5),
            (4750, 21.6, 283.6),
            (5000, 22.4, 289.6),
            (5250, 23.2, 290.9),
            (5500, 23.9, 288.4),
            (5750, 24.3, 282.7),
            (6000, 24.8, 282.2),
            (6250, 25.7, 275.1),
            (6500, 26.6, 269.8),
            (6750, 27.8, 266.0),
            (7000, 28.9, 260.5),
            (7250, 29.2, 249.5),
            (7500, 30.3, 248.7),
        ),
        friction_b=0.07,
        validated=True,
    ),
    VehicleSource(
        vehicle_id="muscle-v8-sc",
        display_name="Muscle V8 5,0 sobrealimentado",
        architecture_note="Inspirado em arquitetura V8 5,0 DOHC com compressor volumétrico",
        body="coupe",
        induction="supercharger",
        architecture="v",
        n_cyl=8,
        v_angle=90.0,
        bore=92.2,
        stroke=92.7,
        rod=150.7,
        cr=9.5,
        displacement=4951.0,
        valvetrain="dohc",
        valves=4,
        firing_order=[1, 5, 4, 8, 6, 3, 7, 2],
        vvt=Vvt(50.0, 50.0),
        ivc=50.0,
        evo=50.0,
        injection="pfi",
        trigger="36-1",
        cam_sync="4x",
        throttle_mm=87.0,
        throttle_loc="pre_compressor",
        v_intake=8.0,
        v_boost=None,
        v_exhaust=1.6,
        ic_kind="air_to_water",
        ic_eff=0.78,
        ic_k=30.0,
        recip_g=780.0,
        wiebe_deg=55.0,
        stock_fuel="e27",
        fuels=["e27", "podium", "e0"],
        drive="rwd",
        gears=[3.66, 2.43, 1.69, 1.32, 1.00, 0.65],
        final_drive=3.73,
        tire_m=0.352,
        eta=0.85,
        inertia=3.6,
        turbo=None,
        injector=(1000.0, 400.0, 400.0, 400.0, "manifold", 0.80),
        limits=_limits(1000.0, 90.0, 145.0, 950.0, 7500.0, 7800.0, 8000.0, None, 340.0),
        map_target_kpa=240.0,
        curve_fuel="e27",
        anchors=[
            (2000, 470.0, 0.90, 650),
            (2500, 515.0, 0.875, 685),
            (3000, 560.0, 0.85, 720),
            (3500, 595.0, 0.835, 750),
            (4000, 630.0, 0.82, 780),
            (4500, 650.0, 0.80, 810),
            (5000, 645.0, 0.80, 830),
            (5500, 628.5, 0.795, 845),
            (6000, 612.0, 0.79, 860),
            (6500, 593.6, 0.79, 870),
            (7000, 540.0, 0.79, 875),
            (7500, 490.0, 0.79, 880),
        ],
        rated={
            "peak_power_whp": 460.0,
            "peak_power_rpm": 6500.0,
            "peak_torque_nm": 650.0,
            "peak_torque_rpm_from": 4500.0,
            "peak_torque_rpm_to": 4500.0,
            "power_ceiling_whp": 800.0,
            "power_range_whp": None,
        },
        prd={
            "/engine/displacement_cc": "PRD seção 7, item 4: 4951 cc",
            "/engine/n_cyl": "PRD seção 7, item 4: 8 cilindros",
            "/engine/architecture": "PRD seção 7, item 4: V8",
            "/induction": "PRD seção 7, item 4: compressor volumétrico",
            "/rated/peak_power_whp": "PRD seção 7, item 4: 460 whp de série",
            "/rated/power_ceiling_whp": "PRD seção 7, item 4: até 800 whp",
        },
        estimates={
            "/mechanical_limits/rod_torque_limit_nm": "internos de série (OQ-05)",
            "/mechanical_limits/egt_max_c": "a confirmar (OQ-07)",
        },
        ve_ecu_wot_corr=(
            (1500.0, 1.1156),
            (2000.0, 1.0696),
            (2500.0, 1.115),
            (3000.0, 1.1113),
            (3500.0, 1.1058),
            (4000.0, 1.0996),
            (4500.0, 1.0937),
            (5000.0, 1.0882),
            (5500.0, 1.0836),
            (6000.0, 1.0784),
            (6500.0, 1.077),
            (7000.0, 1.0726),
        ),
        wot=(
            (2000, 24.2, 233.0),
            (2250, 25.4, 215.6),
            (2500, 20.6, 210.5),
            (2750, 16.9, 208.8),
            (3000, 14.6, 206.4),
            (3250, 14.1, 204.4),
            (3500, 14.1, 202.2),
            (3750, 14.2, 200.5),
            (4000, 15.1, 198.9),
            (4250, 15.9, 197.9),
            (4500, 16.5, 196.8),
            (4750, 16.9, 196.4),
            (5000, 18.0, 196.1),
            (5250, 18.7, 196.6),
            (5500, 19.1, 197.4),
            (5750, 20.4, 199.2),
            (6000, 21.6, 201.3),
            (6250, 23.1, 204.4),
            (6500, 24.3, 208.3),
            (6750, 25.0, 214.4),
            (7000, 25.3, 221.3),
            (7250, 25.2, 228.6),
            (7500, 26.0, 235.2),
        ),
        friction_b=0.05,
        validated=True,
        supercharger=Supercharger(
            displacement_l=2.65,
            pulley_ratio=2.10,
            k_leak=0.20,
            adiabatic_eta=((1.0, 1.25, 1.5, 1.75, 2.0), (0.74, 0.73, 0.71, 0.68, 0.65)),
            mech_eta=0.90,
        ),
    ),
)
"""Fontes por veículo. Âncoras A.4 a 500 rpm; os pontos marcados entre âncoras da spec
(ex.: 2500 rpm do muscle) são a interpolação linear das âncoras publicadas."""


# =========================================================================== curvas


def _anchor_series(src: VehicleSource) -> tuple[list[float], list[float], list[float], list[float]]:
    rpm = [float(a[0]) for a in src.anchors]
    return (
        rpm,
        [a[1] for a in src.anchors],
        [a[2] for a in src.anchors],
        [float(a[3]) for a in src.anchors],
    )


def curve_points(src: VehicleSource) -> list[dict[str, float]]:
    """Pontos de 250 em 250 rpm: torque, lambda e EGT interpolados; potência recalculada."""
    rpm_a, tq_a, lam_a, egt_a = _anchor_series(src)
    points = []
    rpm = rpm_a[0]
    while rpm <= rpm_a[-1] + 1e-9:
        torque = _r(interp_linear(rpm_a, tq_a, rpm), 1)
        p_wheel = crank_power_kw(torque, rpm) * src.eta  # perda fixa 0 kW
        points.append({
            "rpm": float(rpm),
            "torque_crank_nm": torque,
            "power_wheel_kw": _r(p_wheel, 2),
            "lambda_value": _r(interp_linear(rpm_a, lam_a, rpm), 3),
            "egt_c": _r(interp_linear(rpm_a, egt_a, rpm), 1),
        })  # fmt: skip
        rpm += 250.0
    return points


def build_curve(src: VehicleSource) -> dict[str, Any]:
    return {
        "curve_id": f"stock-{src.curve_fuel}",
        "vehicle_id": src.vehicle_id,
        "calibration_ref": "stock",
        "fuel_id": src.curve_fuel,
        "conditions": {"correction": "sae_j1349", "ambient_temp_c": 25.0,
                       "ambient_pressure_kpa": 99.0, "dyno_type": "inertial_roller", "gear": 4},
        "quantities": ["torque_crank_nm", "power_wheel_kw", "lambda_value", "egt_c"],
        "points": curve_points(src),
        "source": INTERNAL_ESTIMATE,
        "license": "internal-estimate",
        "confidence": "estimated",
        "quantity_confidence": {},
        "tolerance_pct": 5.0,
        "benchmark_id": "reference-benchmark-baseline-v1",
    }  # fmt: skip


# =========================================================================== modelo da ECU


@dataclass(frozen=True)
class EngineModel:
    """Relações usadas para tornar o schedule e a calibração OEM coerentes com a curva."""

    src: VehicleSource
    ve: Grid2D

    @property
    def v_cyl_m3(self) -> float:
        return self.src.displacement * 1e-6 / self.src.n_cyl

    def torque_ref(self, rpm: float) -> float:
        rpm_a, tq_a, _, _ = _anchor_series(self.src)
        return interp_linear(rpm_a, tq_a, rpm)

    def lambda_ref(self, rpm: float) -> float:
        rpm_a, _, lam_a, _ = _anchor_series(self.src)
        return interp_linear(rpm_a, lam_a, rpm)

    @property
    def torque_max(self) -> float:
        return max(a[1] for a in self.src.anchors)

    def _wot(self, column: int, rpm: float) -> float:
        if not self.src.wot:
            raise ValueError(f"{self.src.vehicle_id}: tabela de plena carga (wot) ausente")
        return interp_linear([w[0] for w in self.src.wot], [w[column] for w in self.src.wot], rpm)

    def map_wot(self, rpm: float) -> float:
        """MAP alvo a plena carga afinado contra a física (tabela ``wot``, teto A.3)."""
        return _clip(self._wot(2, rpm), 100.0, self.src.map_target_kpa)

    def ign_wot(self, rpm: float) -> float:
        """Avanço de série a plena carga afinado contra a física (tabela ``wot``)."""
        return self._wot(1, rpm)

    def ve_at(self, rpm: float, map_kpa: float) -> float:
        """VE do modelo da ECU: grade de série com a correção de plena carga."""
        ve = interp2d(self.ve, rpm, map_kpa)
        corr = self.src.ve_ecu_wot_corr
        if not corr:
            return ve
        k = interp_linear([c[0] for c in corr], [c[1] for c in corr], rpm)
        return ve * (1.0 + (k - 1.0) * _clip((map_kpa - 100.0) / 100.0, 0.0, 1.0))

    def load_pct(self, rpm: float, map_kpa: float) -> float:
        """Carga relativa: ``m_air / m_ref · 100`` com ``ρ_ref`` a 101,325 kPa e 0 °C."""
        return self.ve_at(rpm, map_kpa) * map_kpa / BARO_KPA * T_REF_K / T_CHARGE_K * 100.0

    def map_for_load(self, rpm: float, load: float) -> float:
        p = load / 100.0 * BARO_KPA
        for _ in range(40):
            p = load / 100.0 * BARO_KPA * T_CHARGE_K / T_REF_K / self.ve_at(rpm, p)
        return p

    def friction_nm(self, rpm: float, ect_c: float = 90.0) -> float:
        """Chen-Flynn: FMEP = c + a·p_max + b·S_p + q·S_p² (bar), p_max 80 bar."""
        sp = 2.0 * self.src.stroke / 1000.0 * rpm / 60.0
        fmep_bar = 0.25 + 0.005 * 80.0 + self.src.friction_b * sp + 0.0009 * sp * sp
        cold = 1.0 + 0.5 * max(0.0, (90.0 - ect_c) / 110.0)
        return fmep_bar * 1e5 * self.src.displacement * 1e-6 / (4.0 * math.pi) * cold

    def ign_base(self, rpm: float, map_kpa: float) -> float:
        """Avanço base: o de plena carga ancorado no MAP de plena carga, +0,08 °/kPa abaixo."""
        map_w = self.map_wot(rpm)
        slope = 0.08 if map_kpa <= map_w else self.src.ign_slope_above_wot
        return _clip(self.ign_wot(rpm) + slope * (map_w - map_kpa), -5.0, 45.0)

    def mbt(self, rpm: float, map_kpa: float) -> float:
        """MBT do modelo da ECU, nunca abaixo do avanço base + 2° (margem de detonação)."""
        formula = 40.0 - 0.075 * map_kpa + 1.2 * rpm / 1000.0
        return _clip(max(formula, self.ign_base(rpm, map_kpa) + 2.0), 8.0, 50.0)

    def cam_intake(self, rpm: float) -> float:
        if self.src.vvt is None:
            return 0.0
        span = self.src.limits["max_rpm"] - 800.0  # type: ignore[operator]
        frac = _clip(0.8 - 0.6 * (rpm - 800.0) / span, 0.1, 0.8)
        return min(self.src.vvt.intake_max * frac, 56.0)

    def cam_exhaust(self, rpm: float) -> float:
        if self.src.vvt is None or self.src.vvt.exhaust_max is None:
            return 0.0
        span = self.src.limits["max_rpm"] - 800.0  # type: ignore[operator]
        frac = _clip(0.2 + 0.4 * (rpm - 800.0) / span, 0.0, 0.6)
        return min(self.src.vvt.exhaust_max * frac, 56.0)

    def wastegate_duty(self, map_kpa: float) -> float:
        if self.src.turbo is None:
            return 0.0
        crack = BARO_KPA + self.src.turbo.spring_kpa
        if map_kpa <= crack:
            return 0.0
        return _clip(20.0 + 60.0 * (map_kpa - crack) / (self.src.map_target_kpa - crack), 0.0, 95.0)


def eta_ign(delta_deg: float) -> float:
    """Eficiência de ignição: ``max(0,05, 1 − 0,00045·Δ²)``."""
    return max(0.05, 1.0 - 0.00045 * delta_deg * delta_deg)


# =========================================================================== veículo JSON


def _grid1d(x_name: str, xs: Sequence[float], values: Sequence[float]) -> dict[str, Any]:
    return {"x_name": x_name, "x_values": list(xs), "values": list(values)}


def _grid2d(  # noqa: PLR0917
    x_name: str,
    xs: Sequence[float],
    y_name: str,
    ys: Sequence[float],
    fn: Callable[[float, float], float],
    nd: int,
) -> dict[str, Any]:
    return {"x_name": x_name, "x_values": list(xs), "y_name": y_name, "y_values": list(ys),
            "z_values": [[_r(fn(x, y), nd) for x in xs] for y in ys]}  # fmt: skip


def _schedule(model: EngineModel) -> dict[str, Any]:
    src = model.src
    points = []
    for p in curve_points(src):
        rpm = p["rpm"]
        map_kpa = model.map_wot(rpm)
        points.append({
            "rpm": rpm,
            "throttle_pct": 100.0,
            "ignition_advance_deg": _r(model.ign_base(rpm, map_kpa), 1),
            "lambda_target": _r(model.lambda_ref(rpm), 3),
            "map_target_kpa": _r(map_kpa, 1),
            "wastegate_duty_pct": _r(model.wastegate_duty(map_kpa), 1),
            "vvt_intake_deg": _r(model.cam_intake(rpm), 1),
            "vvt_exhaust_deg": _r(model.cam_exhaust(rpm), 1),
            "injection_end_deg_btdc": 300.0 if src.injection == "gdi" else None,
        })  # fmt: skip
    return {"vehicle_id": src.vehicle_id, "fuel_id": src.curve_fuel, "points": points}


def _dead_time_grid(src: VehicleSource) -> dict[str, Any]:
    _, dp_ref, _, _, _, t14 = src.injector
    volts = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
    if src.injection == "gdi":
        dps = [5000.0, 10_000.0, 15_000.0, 20_000.0]
    else:
        dps = [200.0, 300.0, 400.0, 500.0]

    def fn(v: float, dp: float) -> float:
        return float(t14 * (14.0 / v) ** 1.5 * (1.0 + 0.10 * (dp / dp_ref - 1.0)))

    return _grid2d("battery_v", volts, "dp_kpa", dps, fn, 3)


def _vvt(model: EngineModel) -> dict[str, Any] | None:
    src = model.src
    if src.vvt is None:
        return None
    xs = model.ve.x_values
    cams = _linspace(0.0, src.vvt.intake_max, 6, 1)

    def g(rpm: float, cam: float) -> float:
        opt = model.cam_intake(rpm)
        return _clip(1.0 - 2.0 * ((cam - opt) / src.vvt.intake_max) ** 2, -1.0, 1.0)  # type: ignore[union-attr]

    return {
        "intake_min_deg": 0.0,
        "intake_max_deg": src.vvt.intake_max,
        "exhaust_min_deg": 0.0 if src.vvt.exhaust_max is not None else None,
        "exhaust_max_deg": src.vvt.exhaust_max,
        "actuator_tau_s": 0.15,
        "k_vvt": 0.06,
        "g_vvt": _grid2d("rpm", xs, "cam_deg", cams, g, 3),
    }


def _turbo(src: VehicleSource) -> dict[str, Any] | None:
    t = src.turbo
    if t is None:
        return None
    return {
        "housing": t.housing,
        "compressor_ar": t.compressor_ar,
        "turbine_ar": t.turbine_ar,
        "rotor_inertia_kg_m2": t.rotor_inertia,
        "bearing_friction_k": t.bearing_k,
        "turbine_area_eff_cm2": t.turbine_area,
        "turbine_efficiency": _grid1d("pressure_ratio", *t.turbine_eta),
        "wastegate_kind": t.wastegate_kind,
        "wastegate_area_max_cm2": t.wastegate_area,
        "wastegate_spring_kpa": t.spring_kpa,
        "wastegate_full_open_delta_kpa": t.full_open_delta_kpa,
        "blow_off_valve": True,
        "compressor": {
            "pr_design": t.pr_design, "n_design_rpm": t.n_design, "n_max_rpm": t.n_max,
            "m_choke_max_kg_s": t.m_choke, "eta_max": t.eta_max, "m_peak_kg_s": t.m_pk,
            "m_range_kg_s": t.m_range, "k1": t.k1, "k2": 0.4,
            "n_peak_rpm": _r(0.8 * t.n_design, 1), "table": None,
        },
    }  # fmt: skip


def _supercharger(src: VehicleSource) -> dict[str, Any] | None:
    sc = src.supercharger
    if src.induction != "supercharger" or sc is None:
        return None
    return {
        "sc_type": "twin_screw", "displacement_l_per_rev": sc.displacement_l,
        "pulley_ratio": sc.pulley_ratio, "k_leak": sc.k_leak, "n_ref_rpm": sc.n_ref,
        "adiabatic_efficiency": _grid1d("pressure_ratio", *sc.adiabatic_eta),
        "mech_efficiency": sc.mech_eta, "bypass_valve": True, "max_rotor_rpm": sc.max_rotor_rpm,
    }  # fmt: skip


def _rated(src: VehicleSource) -> dict[str, Any]:
    rated = dict(src.rated)
    if rated["peak_power_whp"] is None:
        best = max(curve_points(src), key=lambda p: p["power_wheel_kw"])
        rated["peak_power_whp"] = _r(best["power_wheel_kw"] / KW_PER_HP, 1)
        rated["peak_power_rpm"] = best["rpm"]
    return rated


def _provenance(src: VehicleSource) -> dict[str, Any]:
    prov: dict[str, Any] = {}
    for pointer in ("/engine/bore_mm", "/engine/stroke_mm"):
        prov[pointer] = {
            "kind": "public_spec",
            "note": "diâmetro e curso",
            "source": PUBLIC_SPEC_SOURCE,
        }
    prov["/engine/friction"] = {
        "kind": "literature",
        "note": "coeficientes padrão de Chen-Flynn",
        "source": HEYWOOD + ", cap. 13",
    }
    if src.friction_b != CHEN_FLYNN_B:
        prov["/engine/friction/b_bar_s_m"] = {"kind": "estimate", "note": TUNED_NOTE}
    for pointer in (
        "/reference_command_schedule",
        "/engine/true_ve",
        "/engine/wiebe_duration_ref_deg",
        "/turbo",
        "/supercharger",
    ):
        prov[pointer] = {"kind": "estimate", "note": TUNED_NOTE}  # fmt: skip
    if src.turbo is None:
        del prov["/turbo"]
    if src.supercharger is None:
        del prov["/supercharger"]
    for pointer, note in src.estimates.items():
        prov[pointer] = {"kind": "estimate", "note": note}
    for pointer, note in src.prd.items():
        prov[pointer] = {"kind": "prd", "note": note}
    return dict(sorted(prov.items()))


def build_vehicle(src: VehicleSource, calibration_refs: list[dict[str, str]]) -> dict[str, Any]:
    lim = src.limits
    ve = ve_grid(src.vehicle_id, float(lim["max_rpm"]))  # type: ignore[arg-type]
    model = EngineModel(src, ve)
    flow, dp_ref, rail_min, rail_max, ref, _ = src.injector
    mbt = _grid2d("rpm", ve.x_values, "map_kpa", ve.y_values, model.mbt, 1)
    engine = {
        "architecture": src.architecture, "n_cyl": src.n_cyl, "v_angle_deg": src.v_angle,
        "bore_mm": src.bore, "stroke_mm": src.stroke, "rod_length_mm": src.rod,
        "compression_ratio": src.cr, "displacement_cc": src.displacement,
        "valvetrain": src.valvetrain, "valves_per_cyl": src.valves,
        "firing_order": src.firing_order, "ivc_deg_abdc": src.ivc, "evo_deg_bbdc": src.evo,
        "vvt": _vvt(model), "injection_type": src.injection,
        "throttle_diameter_mm": src.throttle_mm, "throttle_location": src.throttle_loc,
        "intake_manifold_volume_l": src.v_intake, "boost_volume_l": src.v_boost,
        "exhaust_manifold_volume_l": src.v_exhaust,
        "intercooler": {"kind": src.ic_kind, "effectiveness": src.ic_eff,
                        "k_dp_kpa_per_kgps2": src.ic_k},
        "recip_mass_g": src.recip_g, "true_ve": ve.model_dump(mode="json"),
        "mbt_reference": mbt, "wiebe_duration_ref_deg": src.wiebe_deg,
        "wiebe_rpm_ref": 3000.0,
        "friction": {"c_bar": 0.25, "a": 0.005, "b_bar_s_m": src.friction_b,
                     "q_bar_s2_m2": 0.0009},
        "crank_trigger": src.trigger, "cam_sync": src.cam_sync,
    }  # fmt: skip
    return {
        "vehicle_id": src.vehicle_id,
        "display_name": src.display_name,
        "architecture_note": src.architecture_note,
        "body": src.body,
        "data_version": 1,
        "validation_status": "validated" if src.validated else "draft",
        "validated_on": VALIDATED_ON if src.validated else None,
        "induction": src.induction,
        "engine": engine,
        "turbo": _turbo(src),
        "supercharger": _supercharger(src),
        "injectors": {
            "count_per_cyl": 1, "flow_cc_min": flow, "dp_ref_kpa": dp_ref,
            "rail_pressure_min_kpa": rail_min, "rail_pressure_max_kpa": rail_max,
            "pressure_reference": ref, "dead_time_ms": _dead_time_grid(src),
            "min_pulse_ms": 0.3 if src.injection == "gdi" else 0.5, "max_duty_pct": 85.0,
        },
        "stock_fuel_id": src.stock_fuel,
        "allowed_fuel_ids": src.fuels,
        "drive_layout": src.drive,
        "gear_ratios": src.gears,
        "final_drive_ratio": src.final_drive,
        "tire_radius_m": src.tire_m,
        "drivetrain_efficiency": src.eta,
        "drivetrain_fixed_loss_kw": 0.0,
        "driveline_inertia_kg_m2": src.inertia,
        "mechanical_limits": lim,
        "rated": _rated(src),
        "stock_profile_id": "oem-stage",
        "stock_calibration_id": f"stock-{src.vehicle_id}-oem-stage",
        "factory_calibrations": calibration_refs,
        "reference_command_schedule": _schedule(model),
        "reference_curve_ids": [f"stock-{src.curve_fuel}"],
        "provenance": _provenance(src),
    }  # fmt: skip


# =========================================================================== calibrações


def _round_tree(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _round_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_tree(v) for v in value]
    return value


def calibration_content_hash(cal: dict[str, Any]) -> str:
    """``content_hash`` do ecu-core: payload sem metadados, floats a 6 casas."""
    keys = ("vehicle_id", "profile_id", "fuel_model", "tables", "strategies", "profile_params")
    return canonical_sha256(_round_tree({k: cal[k] for k in keys}))


def oem_checksum(content_hash: str) -> str:
    """ecu-profiles RF-12: ``crc32(content_hash + ":oem-stage")`` em 8 hex."""
    return f"{zlib.crc32((content_hash + ':oem-stage').encode('utf-8')) & 0xFFFFFFFF:08x}"


_UNITS: Final[dict[str, tuple[str, bool, int]]] = {
    # kind: (unidade do Apêndice A do ecu-core, live_tunable padrão, decimais)
    "ve": ("%", True, 1), "inj_base_ms": ("ms", True, 3), "lambda_target": ("λ", True, 3),
    "ignition_base": ("°BTDC", True, 1), "ign_corr_iat": ("°", True, 1),
    "fuel_corr_ect": ("%", False, 1), "accel_enrich": ("%", False, 1),
    "cranking_fuel": ("ms", False, 2), "afterstart_enrich": ("%", False, 1),
    "inj_dead_time": ("ms", False, 3), "boost_target": ("kPa", True, 0),
    "boost_target_gear": ("kPa", True, 0), "boost_duty_base": ("%", False, 1),
    "knock_threshold": ("adimensional", False, 2), "oil_pressure_min": ("kPa", False, 0),
    "cam_intake_target": ("°", True, 1), "cam_exhaust_target": ("°", True, 1),
    "torque_request": ("N·m", True, 1), "torque_limit": ("N·m", True, 1),
    "torque_limit_gear": ("N·m", True, 1), "torque_optimal": ("N·m", False, 1),
    "ignition_optimal": ("°BTDC", True, 1), "ignition_efficiency": ("adimensional", False, 3),
    "oem_pressure_target": ("kPa", True, 0), "friction_torque": ("N·m", False, 1),
    "lambda_component_protection": ("λ", True, 3),
}  # fmt: skip


def _table2d(
    kind: str, quantity: str, xs: Sequence[float], values: Sequence[float], description: str
) -> dict[str, Any]:
    unit, live, nd = _UNITS[kind]
    return {"table_id": kind, "kind": kind, "unit": unit, "live_tunable": live, "cylinder": None,
            "description": description, "decimals": nd, "dims": 2,
            "x": {"quantity": quantity, "values": [float(x) for x in xs]},
            "values": [_r(v, max(nd, 3)) for v in values]}  # fmt: skip


def _table3d(  # noqa: PLR0917
    kind: str,
    xq: str,
    xs: Sequence[float],
    yq: str,
    ys: Sequence[float],
    fn: Callable[[float, float], float],
    description: str,
) -> dict[str, Any]:
    unit, live, nd = _UNITS[kind]
    return {"table_id": kind, "kind": kind, "unit": unit, "live_tunable": live, "cylinder": None,
            "description": description, "decimals": nd, "dims": 3,
            "x": {"quantity": xq, "values": [float(x) for x in xs]},
            "y": {"quantity": yq, "values": [float(y) for y in ys]},
            "values": [[_r(fn(x, y), max(nd, 3)) for x in xs] for y in ys]}  # fmt: skip


def _common_corrections() -> list[dict[str, Any]]:
    return [
        _table2d(
            "ign_corr_iat",
            "iat_c",
            [-20, 0, 20, 40, 60, 80, 100],
            # 0° na faixa de carga quente de referência (40–60 °C): a tabela wot foi afinada
            # na física com a IAT real da plena carga; retardo só acima (heat soak)
            [3.0, 2.0, 1.0, 0.0, 0.0, -1.0, -4.0],
            "Correção de avanço pela IAT",
        ),
        _table2d(
            "fuel_corr_ect",
            "ect_c",
            [-20, 0, 20, 40, 60, 80, 90, 110],
            [40.0, 25.0, 12.0, 5.0, 2.0, 0.0, 0.0, 0.0],
            "Enriquecimento a frio",
        ),
        _table2d(
            "cranking_fuel",
            "ect_c",
            [-20, 0, 20, 40, 60, 80],
            [12.0, 9.0, 6.0, 4.0, 3.0, 2.5],
            "Pulso de partida",
        ),
        _table2d(
            "afterstart_enrich",
            "ect_c",
            [-20, 0, 20, 40, 60, 80],
            [40.0, 30.0, 20.0, 10.0, 5.0, 0.0],
            "Enriquecimento pós-partida",
        ),
        _table2d(
            "accel_enrich",
            "tps_rate_pct_s",
            [0, 50, 100, 200, 400, 800],
            [0.0, 5.0, 10.0, 20.0, 35.0, 50.0],
            "Enriquecimento de aceleração",
        ),
    ]


def _oil_and_knock(rpms: Sequence[float], rev: float) -> list[dict[str, Any]]:
    return [
        _table2d(
            "knock_threshold",
            "rpm",
            rpms,
            # escala de ``SensorReadings.knock_intensity`` (0–1, D-BUS-05): o limiar de
            # 1,0–1,5 bar de MAPO convertido pelo sensor da física (1,5 V/bar em 0–4,95 V)
            [round((1.0 + 0.5 * r / rev) * KNOCK_SENSOR_BAR_TO_INDEX, 4) for r in rpms],
            "Limiar de detonação",
        ),
        _table2d(
            "oil_pressure_min",
            "rpm",
            rpms,
            [50.0 + 30.0 * r / 1000.0 for r in rpms],
            "Pressão mínima de óleo",
        ),
    ]


def _failsafe(lim: dict[str, float | None]) -> dict[str, Any]:
    egt = float(lim["egt_max_c"])  # type: ignore[arg-type]
    max_rpm = float(lim["max_rpm"])  # type: ignore[arg-type]

    def rule(  # noqa: PLR0917
        rule_id: str,
        threshold: float,
        confirm: float,
        actions: list[str],
        value: float,
        release: float,
        latch: bool = False,
    ) -> dict[str, Any]:
        return {"rule_id": rule_id, "enabled": True, "threshold": threshold,
                "confirm_s": confirm, "actions": actions, "action_value": value,
                "release_s": release, "latch_until_stop": latch}  # fmt: skip

    return {
        "enabled": True, "kind": "failsafe", "overspeed_rpm": max_rpm,
        "rules": [
            rule("egt_high", egt, 0.5, ["boost_reduce", "enrich"], 30.0, 2.0),
            rule("egt_critical", egt + 30.0, 0.2, ["boost_cut", "rev_limit_reduce"], 4000.0, 5.0),
            rule("lean_under_load", 0.10, 0.3, ["boost_cut"], 0.0, 2.0),
            rule("ect_high", 110.0, 1.0, ["boost_reduce", "rev_limit_reduce"], 4500.0, 10.0),
            rule("oil_pressure_low", 0.0, 0.5, ["fuel_cut"], 0.0, 0.0, latch=True),
            rule("overspeed", max_rpm, 0.0, ["fuel_cut"], 0.0, 0.0),
            rule("sensor_fault", 0.05, 0.05, ["boost_cut", "rev_limit_reduce"], 3000.0, 2.0),
        ],
    }  # fmt: skip


# Ganhos do PID de boost OEM por veículo (kp %/kPa, ki %/(kPa·s), kd %·s/kPa). Hatch
# (B5, 003 T032): 0,4/0,8/0,1 fazia um ciclo-limite de 7,5 Hz com a wastegate (desvio do
# torque ±12 N·m em plena carga; com duty fixo a física é estável); 0,1/0,3/0 tira a
# oscilação (±0,4 N·m) com 214,7 whp de série. O coupé e o clássico pioram com estes
# ganhos (afinação própria pendente) e o V8 não tem turbo.
BOOST_PID_GAINS: Final[dict[str, tuple[float, float, float]]] = {
    "hatch-20t-gdi": (0.1, 0.3, 0.0),
}


def _boost_config(vehicle_id: str, overboost: float) -> BoostControlConfig:
    gains = BOOST_PID_GAINS.get(vehicle_id)
    if gains is None:
        # termo D 0,1 %·s/kPa (padrão 0,02): amortece o enchimento do turbo; com 0,02 um
        # alvo acima da série ultrapassava-o em 40–55 kPa (sobrevelocidade do turbo)
        return BoostControlConfig(overboost_kpa=overboost, kd_pct_s_per_kpa=0.1)
    kp, ki, kd = gains
    return BoostControlConfig(
        overboost_kpa=overboost, kp_pct_per_kpa=kp, ki_pct_per_kpa_s=ki, kd_pct_s_per_kpa=kd
    )


def _strategies(
    lim: dict[str, float | None], overboost: float, *, standalone: bool, vehicle_id: str
) -> dict[str, Any]:
    rev = float(lim["rev_limit_rpm"])  # type: ignore[arg-type]
    models: list[Any] = [
        ClosedLoopConfig(rpm_max=rev, map_max_kpa=110.0 if not standalone else 400.0),
        KnockControlConfig(),
        _boost_config(vehicle_id, overboost),
        RevLimiterConfig(hard_rpm=rev),
        OverrunConfig(),
        FailsafeConfig.model_validate(_failsafe(lim)),
    ]
    if standalone:
        models += [TwoStepConfig(enabled=False), AntilagConfig(enabled=False),
                   PowershiftConfig(enabled=False)]  # fmt: skip
    order = ("closed_loop", "knock_control", "boost_control", "rev_limiter", "two_step",
             "antilag", "powershift", "overrun", "failsafe")  # fmt: skip
    dumped = {m.kind: m.model_dump(mode="json") for m in models}
    return {k: dumped[k] for k in order if k in dumped}


def _fuel_model(mode: str) -> dict[str, Any]:
    return {"mode": mode, "charge_temp_blend": 0.0, "accel_enrich_tau_s": 0.2,
            "afterstart_decay_s": 15.0, "cranking_rpm": 400.0, "cranking_ign_deg": 10.0,
            "inj_duty_warn_pct": 85.0}  # fmt: skip


def _finish(cal: dict[str, Any]) -> dict[str, Any]:
    content_hash = calibration_content_hash(cal)
    if cal["profile_id"] == "oem-stage":
        cal["metadata"]["extra"] = {"oem_checksum": oem_checksum(content_hash)}
    cal["content_hash"] = content_hash
    cal["created_at"] = CALIBRATION_CREATED_AT
    return cal


def build_oem_calibration(src: VehicleSource) -> dict[str, Any]:
    """Calibração de série ``oem-stage`` coerente com a curva e o schedule de referência."""
    lim = src.limits
    rev = float(lim["rev_limit_rpm"])  # type: ignore[arg-type]
    ve = ve_grid(src.vehicle_id, float(lim["max_rpm"]))  # type: ignore[arg-type]
    m = EngineModel(src, ve)
    rpms = _linspace(500.0, round(rev / 100.0) * 100.0, 16, 3)
    loads_wot = [m.load_pct(r, m.map_wot(r)) for r in rpms]
    load_max = min(300.0, math.ceil(1.4 * max(loads_wot) / 10.0) * 10.0)
    pedals = [0, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 95, 100]
    map_top = max(320.0, src.map_target_kpa + 20.0)
    maps = _linspace(20.0, map_top, 16, 3)
    ects = [-20, -10, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]
    deltas = [3.0 * i for i in range(16)]
    gears = list(range(1, len(src.gears) + 1))
    t_max = m.torque_max
    # torque_limit (2D, até 32 pontos) nos RPM da curva de série, mais 500 rpm abaixo dela.
    curve_rpms = [p["rpm"] for p in curve_points(src)]
    limit_rpms = [r for r in (500.0, 1000.0, 1500.0, 2000.0, 2500.0) if r < curve_rpms[0]]
    limit_rpms += curve_rpms

    def ign_base_load(rpm: float, load: float) -> float:
        return m.ign_base(rpm, m.map_for_load(rpm, load))

    def ign_opt_load(rpm: float, load: float) -> float:
        p = m.map_for_load(rpm, load)
        return max(m.mbt(rpm, p), m.ign_base(rpm, p))

    def k_torque(rpm: float) -> float:
        map_w = m.map_wot(rpm)
        load_w = m.load_pct(rpm, map_w)
        eta_w = eta_ign(ign_opt_load(rpm, load_w) - ign_base_load(rpm, load_w))
        return (m.torque_ref(rpm) + m.friction_nm(rpm)) / (load_w * eta_w)

    # Eixo de carga até 1,4 × a carga de plena carga, limitado para torque_optimal ≤ 1450 N·m.
    k_max = max(k_torque(r) for r in rpms)
    load_max = min(load_max, math.floor(1450.0 / k_max / 10.0) * 10.0)
    if load_max < 1.1 * max(loads_wot):
        raise ValueError(f"{src.vehicle_id}: eixo de carga sem folga sobre a plena carga")
    loads = _linspace(10.0, load_max, 16, 3)

    def lam(rpm: float, map_kpa: float) -> float:
        """λ = 1 até 60 kPa; transição linear até 100 kPa; acima, o λ de plena carga."""
        lam_w = m.lambda_ref(rpm)
        return 1.0 + (lam_w - 1.0) * _clip((map_kpa - LAMBDA_BLEND_LOW) / 40.0, 0.0, 1.0)

    egt_max = float(lim["egt_max_c"])  # type: ignore[arg-type]
    boost_targets = _linspace(100.0, src.map_target_kpa + 60.0, 16, 3)

    def duty(rpm: float, target: float) -> float:
        if src.turbo is None:
            return _clip((target - BARO_KPA) / (src.map_target_kpa - BARO_KPA) * 100.0, 0.0, 100.0)
        base = (
            m.wastegate_duty(target)
            if target < src.map_target_kpa
            else _clip(80.0 + 15.0 * (target - src.map_target_kpa) / 60.0, 0.0, 95.0)
        )
        return _clip(base * (1.0 + 0.2 * (1.0 - rpm / rev)), 0.0, 100.0)

    tables = [
        _table3d(
            "torque_request",
            "rpm",
            rpms,
            "pedal_pct",
            pedals,
            lambda r, p: (p / 100.0) ** 1.1 * 1.10 * t_max,
            "Pedido de torque do pedal",
        ),
        _table2d(
            "torque_limit",
            "rpm",
            limit_rpms,
            [m.torque_ref(r) for r in limit_rpms],
            "Limite de torque por rotação (curva de série)",
        ),
        _table2d(
            "torque_limit_gear",
            "gear",
            gears,
            [
                0.75 * t_max if g == 1 else 0.90 * t_max if g == 2 else 1.10 * t_max  # noqa: PLR2004
                for g in gears
            ],
            "Limite de torque por marcha",
        ),
        _table3d(
            "torque_optimal",
            "rpm",
            rpms,
            "load_pct",
            loads,
            lambda r, ld: k_torque(r) * ld,
            "Torque indicado no avanço ótimo",
        ),
        _table3d(
            "ignition_optimal",
            "rpm",
            rpms,
            "load_pct",
            loads,
            ign_opt_load,
            "Avanço ótimo (MBT) por carga",
        ),
        _table3d(
            "ignition_base", "rpm", rpms, "load_pct", loads, ign_base_load, "Avanço base por carga"
        ),
        _table2d(
            "ignition_efficiency",
            "ign_delta_deg",
            deltas,
            [eta_ign(d) for d in deltas],
            "Eficiência de torque pelo atraso face ao ótimo",
        ),
        _table3d(
            "oem_pressure_target",
            "rpm",
            rpms,
            "load_pct",
            loads,
            lambda r, ld: _clip(m.map_for_load(r, ld), 80.0, 400.0),
            "Pressão alvo do coletor pela carga alvo",
        ),
        _table3d(
            "friction_torque",
            "rpm",
            rpms,
            "ect_c",
            ects,
            m.friction_nm,
            "Torque de atrito (Chen-Flynn)",
        ),
        _table2d(
            "lambda_component_protection",
            "egt_c",
            [600.0, egt_max - 30.0, egt_max, egt_max + 50.0],
            [1.30, 1.30, 0.82, 0.75],
            "Lambda de proteção de componentes pela EGT",
        ),
        _table3d("lambda_target", "rpm", rpms, "map_kpa", maps, lam, "Lambda alvo"),
        _table3d(
            "ve",
            "rpm",
            rpms,
            "map_kpa",
            maps,
            lambda r, p: 100.0 * m.ve_at(r, p),
            "Modelo de enchimento de série (VE)",
        ),
        _table2d(
            "inj_dead_time",
            "battery_v",
            [8, 9, 10, 11, 12, 13, 14, 15, 16],
            [src.injector[5] * (14.0 / v) ** 1.5 for v in range(8, 17)],
            "Tempo morto do bico",
        ),
        _table3d(
            "boost_duty_base",
            "rpm",
            rpms,
            "boost_target_kpa",
            boost_targets,
            duty,
            "Duty base da válvula de alívio",
        ),
        *_oil_and_knock(rpms, rev),
        *_common_corrections(),
    ]
    if src.vvt is not None:
        tables.append(
            _table3d(
                "cam_intake_target",
                "rpm",
                rpms,
                "map_kpa",
                maps,
                lambda r, p: m.cam_intake(r) * min(1.0, 0.4 + 0.6 * p / 100.0),
                "Alvo do comando de admissão",
            )
        )
        if src.vvt.exhaust_max is not None:
            tables.append(
                _table3d(
                    "cam_exhaust_target",
                    "rpm",
                    rpms,
                    "map_kpa",
                    maps,
                    lambda r, p: m.cam_exhaust(r),
                    "Alvo do comando de escape",
                )
            )
    cal = {
        "calibration_id": f"stock-{src.vehicle_id}-oem-stage",
        "vehicle_id": src.vehicle_id,
        "profile_id": "oem-stage",
        "version": 1,
        "parent_version": None,
        "fuel_model": _fuel_model("profile_air_model"),
        "tables": {t["table_id"]: t for t in tables},
        "strategies": _strategies(
            lim, src.map_target_kpa + 30.0, standalone=False, vehicle_id=src.vehicle_id
        ),
        "profile_params": {"torque_monitoring": True, "component_protection": True,
                           "knock_protection": True, "overboost_protection": True,
                           "checksum_check": True},
        "metadata": {"name": "Calibração de série OEM-Stage", "author_nickname": None,
                     "notes": "Calibração de fábrica do catálogo (lógica por torque).",
                     "source": "oem_stock", "change_summary": "", "extra": {}},
    }  # fmt: skip
    return _finish(cal)


def build_ftpro_calibration(src: VehicleSource) -> dict[str, Any]:
    """Mapa base ``ft-pro`` (fórmulas do assistente, ecu-profiles Apêndice E)."""
    lim = src.limits
    rev = float(lim["rev_limit_rpm"])  # type: ignore[arg-type]
    fuel = FUELS[src.stock_fuel]
    max_map = 250.0
    rpms = _linspace(500.0, rev, 16, 3)
    maps = _linspace(20.0, max_map + 20.0, 16, 3)
    rpm_pk = 0.6 * rev
    c_fuel = {"e0": 0.0, "e27": 0.0, "podium": 2.0, "e100": 3.0}[src.stock_fuel]
    lam_hi = {"e0": 0.82, "e27": 0.82, "podium": 0.80, "e100": 0.78}[src.stock_fuel]

    def ve_base(rpm: float, map_kpa: float) -> float:
        f_rpm = _clip(0.80 + 0.20 * (1.0 - ((rpm - rpm_pk) / rpm_pk) ** 2), 0.70, 1.00)
        f_map = 0.55 + 0.45 * min(map_kpa / 100.0, 1.0)
        return 85.0 * f_rpm * f_map

    def lam(_rpm: float, map_kpa: float) -> float:
        if map_kpa <= 70.0:  # noqa: PLR2004
            return 1.0
        if map_kpa <= 100.0:  # noqa: PLR2004
            return 1.0 - 0.10 * (map_kpa - 70.0) / 30.0
        return 0.90 + (lam_hi - 0.90) * min((map_kpa - 100.0) / (max_map - 100.0), 1.0)

    def ign(rpm: float, map_kpa: float) -> float:
        adv = (10.0 + 16.0 * min(rpm / 4000.0, 1.0) - 0.12 * max(map_kpa - 60.0, 0.0)
               + c_fuel - 1.5 * max(src.cr - 9.0, 0.0))  # fmt: skip
        return _clip(adv, 5.0, 35.0)

    v_cyl = src.displacement * 1e-6 / src.n_cyl
    flow = src.injector[0]
    q_inj = flow * fuel["density_kg_m3"] / 1000.0 / 60000.0  # g/ms (ΔP real = ΔP_ref)

    def inj_ms(rpm: float, map_kpa: float) -> float:
        m_air_g = (
            ve_base(rpm, map_kpa) / 100.0 * map_kpa * 1000.0 * v_cyl / (R_AIR * 303.15) * 1000.0
        )
        m_fuel_g = m_air_g / (lam(rpm, map_kpa) * fuel["afr_stoich"])
        return float(m_fuel_g / q_inj)

    tps = [0, 5, 10, 20, 30, 40, 50, 60, 70, 75, 80, 85, 90, 95, 98, 100]

    def boost(rpm: float, tp: float) -> float:
        ramp = _clip((rpm - 2000.0) / 1500.0, 0.0, 1.0) * 0.4 + 0.6
        return _clip(
            BARO_KPA + (max_map - BARO_KPA) * _clip((tp - 30.0) / 60.0, 0.0, 1.0) * ramp,
            80.0,
            400.0,
        )

    crack = BARO_KPA + (src.turbo.spring_kpa if src.turbo else 0.0)
    targets = _linspace(100.0, max_map + 40.0, 16, 3)
    gears = list(range(1, len(src.gears) + 1))
    tables = [
        _table3d("ve", "rpm", rpms, "map_kpa", maps, ve_base, "VE do mapa base"),
        _table3d("inj_base_ms", "rpm", rpms, "map_kpa", maps, inj_ms, "Injeção principal (ms)"),
        _table3d("lambda_target", "rpm", rpms, "map_kpa", maps, lam, "Lambda alvo"),
        _table3d("ignition_base", "rpm", rpms, "map_kpa", maps, ign, "Avanço principal"),
        _table2d(
            "inj_dead_time",
            "battery_v",
            [8, 9, 10, 11, 12, 13, 14, 15, 16],
            [src.injector[5] * (14.0 / v) ** 1.5 for v in range(8, 17)],
            "Tempo morto do bico",
        ),
        _table3d("boost_target", "rpm", rpms, "tps_pct", tps, boost, "Alvo de pressão"),
        _table2d(
            "boost_target_gear",
            "gear",
            gears,
            [180.0 if g == 1 else 220.0 if g == 2 else max_map for g in gears],  # noqa: PLR2004
            "Alvo de pressão por marcha",
        ),
        _table3d(
            "boost_duty_base",
            "rpm",
            rpms,
            "boost_target_kpa",
            targets,
            lambda r, t: _clip(100.0 * (t - crack) / (max_map + 40.0 - crack), 0.0, 95.0),
            "Duty base da válvula de alívio",
        ),
        *_oil_and_knock(rpms, rev),
        *_common_corrections(),
    ]
    cal = {
        "calibration_id": f"stock-{src.vehicle_id}-ft-pro",
        "vehicle_id": src.vehicle_id,
        "profile_id": "ft-pro",
        "version": 1,
        "parent_version": None,
        "fuel_model": _fuel_model("direct_pulse_ms"),
        "tables": {t["table_id"]: t for t in tables},
        "strategies": _strategies(lim, 260.0, standalone=True, vehicle_id=src.vehicle_id),
        "profile_params": {},
        "metadata": {"name": "Mapa base FT-Pro do swap", "author_nickname": None,
                     "notes": "Mapa base de fábrica do catálogo (fórmulas do assistente).",
                     "source": "oem_stock", "change_summary": "", "extra": {}},
    }  # fmt: skip
    return _finish(cal)


# =========================================================================== escrita


def build_all(root: Path) -> None:
    """Escreve todos os arquivos de dados em ``root`` e regrava o manifesto."""
    for fuel_id, fuel in FUELS.items():
        write_json(root / "fuels" / f"{fuel_id}.json", fuel)
    for src in VEHICLES:
        vdir = root / "vehicles" / src.vehicle_id
        builders = {"oem-stage": build_oem_calibration, "ft-pro": build_ftpro_calibration}
        refs = []
        for profile_id in ("oem-stage", *src.extra_profiles):
            cal = builders[profile_id](src)
            path = vdir / "calibrations" / f"{profile_id}.json"
            write_json(path, cal)
            refs.append({"profile_id": profile_id, "calibration_id": cal["calibration_id"],
                         "file": f"calibrations/{profile_id}.json",
                         "sha256": sha256_bytes(dumps_pretty(cal).encode("utf-8"))})  # fmt: skip
        write_json(vdir / "reference-curves" / f"stock-{src.curve_fuel}.json", build_curve(src))
        write_json(vdir / "vehicle.json", build_vehicle(src, refs))
    rehash(root, CATALOG_VERSION)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera os dados do catálogo a partir da spec.")
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    parser.add_argument("--force", action="store_true", help="sobrescreve dados existentes")
    args = parser.parse_args(argv)
    if (args.catalog_dir / "manifest.json").exists() and not args.force:
        print("dados já existem; use --force para regenerar", file=sys.stderr)
        return 2
    build_all(args.catalog_dir)
    print(f"catálogo gerado em {args.catalog_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
