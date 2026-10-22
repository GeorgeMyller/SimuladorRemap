"""Fixtures da física: 4 veículos, 4 combustíveis e ``ReferenceCommandSchedule`` (T092).

Os ``VehicleSpec`` são montados a partir das fichas A.1–A.3 e da fórmula de VE A.7 da
spec ``vehicle-catalog`` (o catálogo real em ``catalog/data`` é de outro componente).
Calibração do ``hatch-20t-gdi`` (desvios face às estimativas A.3, necessários para a
física atingir 220 whp / 350 N·m; a repassar ao ``vehicle-catalog``):

- turbina: área efetiva 2,6 cm² (A.3: 7,0) e ``η_t`` 0,62/0,72/0,75/0,72 em PR 1,0/1,5/2,0/3,0;
  com 7,0 cm² o turbo não enche abaixo de 3000 rpm;
- wastegate: área máxima 6,0 cm² (A.3: 3,0) para controlar o boost acima de 5000 rpm e
  ``wastegate_full_open_delta_kpa`` 8 kPa (padrão 40) para duty 0 % segurar a mola ± 5 kPa;
- compressor: ``m_choke_max`` 0,42 kg/s (A.3: 0,22), ``m_peak`` 0,20, ``m_range`` 0,22,
  ``k1`` 0,5; com 0,22 kg/s o compressor não passa de ≈ 0,18 kg/s a PR 2,1, abaixo dos
  ≈ 0,22 kg/s exigidos por 220 whp a 6000 rpm;
- Chen-Flynn: ``b`` 0,07 bar·s/m (padrão 0,09);
- tabela de referência (``HATCH_ANCHORS``): avanço 17–27° BTDC (3–6° atrasado face ao MBT, como uma
  calibração de série limitada por knock), λ da curva v1 e MAP alvo 216–240 kPa por RPM.

Fixtures expostas: ``fuels`` (dict ``fuel_id → FuelSpec``), ``hatch``, ``coupe``,
``classic``, ``muscle``, ``na_vehicle`` (variante aspirada mínima do hatch),
``vehicles`` (os 4 canónicos), ``hatch_schedule``, ``make_engine`` (fábrica),
``run_steady`` e ``sweep`` (auxiliares de regime permanente).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from simremap.catalog.contracts import (
    FuelId,
    FuelSpec,
    Grid1D,
    Grid2D,
    ReferenceCommandPoint,
    ReferenceCommandSchedule,
    VehicleSpec,
)
from simremap.physics.contracts import EngineState, PhysicsConfig
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig

FAKE_SHA = "0" * 64
RPM_AXIS = [
    800,
    1000,
    1250,
    1500,
    1750,
    2000,
    2500,
    3000,
    3500,
    4000,
    4500,
    5000,
    5500,
    6000,
    6500,
    7000,
]
MAP_AXIS = [20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 140, 160, 180, 200, 230, 260]

# --------------------------------------------------------------------------- combustíveis


def _fuel(  # noqa: PLR0917
    fid: FuelId,
    name: str,
    afr: float,
    lhv: float,
    ron: float,
    mon: float,
    kon: float,
    hfg: float,
    rho: float,
    eth: float,
    pre: float,
) -> FuelSpec:
    bm = 0.305 + (0.465 - 0.305) * eth
    bphi = -0.549 + (-1.0 + 0.549) * eth
    phim = 1.21 + (1.10 - 1.21) * eth
    return FuelSpec(
        fuel_id=fid,
        display_name=name,
        afr_stoich=afr,
        lhv_mj_kg=lhv,
        ron=ron,
        mon=mon,
        knock_on=kon,
        h_fg_kj_kg=hfg,
        density_kg_m3=rho,
        ethanol_mass_fraction=eth,
        laminar_bm_m_s=bm,
        laminar_bphi_m_s=bphi,
        laminar_phi_m=phim,
        preignition_surface_temp_c=pre,
    )


FUELS: dict[str, FuelSpec] = {
    "e27": _fuel("e27", "Gasolina comum E27", 13.2, 38.7, 94, 82, 94, 512, 745, 0.28, 880),
    "e100": _fuel("e100", "Etanol E100", 9.0, 26.8, 109, 90, 106, 920, 789, 1.0, 830),
    "podium": _fuel("podium", "Gasolina Podium", 14.4, 42.9, 102, 88, 102, 340, 755, 0.0, 920),
    "e0": _fuel("e0", "Gasolina pura E0", 14.7, 43.4, 95, 85, 95, 350, 740, 0.0, 900),
}

# --------------------------------------------------------------------------- grades


def true_ve_grid(  # noqa: PLR0917
    ve_pk: float,
    rpm_pk: float,
    rpm_span: float,
    k_r: float,
    k_m: float,
    map_c: float,
    rpm_axis: list[int] | None = None,
    map_axis: list[int] | None = None,
) -> Grid2D:
    """Fórmula A.7 de ``tools/gen_ve.py`` (determinística)."""
    xs = rpm_axis or RPM_AXIS
    ys = map_axis or MAP_AXIS
    z = [
        [
            min(
                max(
                    ve_pk
                    * (1 - k_r * ((r - rpm_pk) / rpm_span) ** 2)
                    * (1 - k_m * math.exp(-m / map_c)),
                    0.20,
                ),
                1.35,
            )
            for r in xs
        ]
        for m in ys
    ]
    return Grid2D(
        x_name="rpm",
        x_values=[float(x) for x in xs],
        y_name="map_kpa",
        y_values=[float(y) for y in ys],
        z_values=z,
    )


def g_vvt_grid(cam_max: float) -> Grid2D:
    """Ganho do VVT de admissão: avanço ajuda em baixa, prejudica em alta rotação."""
    rpms = [1000.0, 3000.0, 5000.0, 7000.0]
    cams = [0.0, cam_max / 2, cam_max]
    shape = [1.0, 0.4, -0.3, -0.8]
    z = [[round(min(max(s * c / cam_max, -1.0), 1.0), 4) for s in shape] for c in cams]
    return Grid2D(x_name="rpm", x_values=rpms, y_name="cam_deg", y_values=cams, z_values=z)


def dead_time_grid(at_14v: float) -> Grid2D:
    volts = [8.0, 10.0, 12.0, 14.0, 16.0]
    factors = [2.6, 1.8, 1.3, 1.0, 0.85]
    return Grid2D(
        x_name="battery_v",
        x_values=volts,
        y_name="dp_kpa",
        y_values=[100.0, 30000.0],
        z_values=[[round(at_14v * f, 4) for f in factors]] * 2,
    )


def schedule(
    vehicle_id: str,
    fuel_id: str,
    rows: list[tuple[float, float, float, float]],
    vvt: tuple[float, float] = (0.0, 0.0),
) -> ReferenceCommandSchedule:
    """``rows``: (rpm, avanço, lambda alvo, MAP alvo)."""
    return ReferenceCommandSchedule(
        vehicle_id=vehicle_id,
        fuel_id=fuel_id,  # type: ignore[arg-type]
        points=[
            ReferenceCommandPoint(
                rpm=r,
                ignition_advance_deg=a,
                lambda_target=lam,
                map_target_kpa=m,
                vvt_intake_deg=vvt[0],
                vvt_exhaust_deg=vvt[1],
            )
            for r, a, lam, m in rows
        ],
    )


def _expand(
    anchors: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    """Interpola âncoras de 500 rpm para o passo de 250 rpm do catálogo."""
    out: list[tuple[float, float, float, float]] = []
    for (r0, a0, l0, m0), (r1, a1, l1, m1) in itertools.pairwise(anchors):
        steps = round((r1 - r0) / 250)
        for k in range(steps):
            f = k / steps
            out.append((r0 + 250 * k, a0 + (a1 - a0) * f, l0 + (l1 - l0) * f, m0 + (m1 - m0) * f))
    out.append(anchors[-1])
    return out


# Calibração de série do hatch (avanço ° BTDC, lambda alvo da curva v1, MAP alvo calibrado).
HATCH_ANCHORS: list[tuple[float, float, float, float]] = [
    (2000, 17.0, 0.95, 228.0),
    (2500, 18.0, 0.95, 219.0),
    (3000, 18.0, 0.95, 216.0),
    (3500, 18.5, 0.93, 218.0),
    (4000, 19.0, 0.90, 222.0),
    (4500, 20.0, 0.88, 228.0),
    (5000, 21.5, 0.85, 236.0),
    (5500, 23.0, 0.83, 240.0),
    (6000, 25.0, 0.82, 238.0),
    (6500, 27.0, 0.82, 230.0),
]
HATCH_SCHEDULE = _expand(HATCH_ANCHORS)


def _calibration_refs(vehicle_id: str, profiles: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": p,
            "calibration_id": f"stock-{vehicle_id}-{p}",
            "file": f"calibrations/{p}.json",
            "sha256": FAKE_SHA,
        }
        for p in profiles
    ]


def _base(vehicle_id: str, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "body": "hatch",
        "data_version": 1,
        "validation_status": "draft",
        "stock_profile_id": "oem-stage",
        "stock_calibration_id": f"stock-{vehicle_id}-oem-stage",
        "factory_calibrations": _calibration_refs(vehicle_id, ["oem-stage"]),
        "reference_curve_ids": ["stock-e27"],
        "drivetrain_fixed_loss_kw": 0.0,
    }
    data.update(over)
    return data


def build_hatch() -> VehicleSpec:
    vid = "hatch-20t-gdi"
    return VehicleSpec.model_validate(
        _base(
            vid,
            display_name="Hatch 2.0 turbo GDI",
            architecture_note="Inspirado em arquitetura 2.0 turbo GDI de 4 cilindros",
            validation_status="validated",
            validated_on="2026-10-25",
            induction="turbo",
            engine={
                "architecture": "inline",
                "n_cyl": 4,
                "bore_mm": 82.5,
                "stroke_mm": 92.8,
                "rod_length_mm": 144.0,
                "compression_ratio": 9.6,
                "displacement_cc": 1984,
                "valvetrain": "dohc",
                "valves_per_cyl": 4,
                "firing_order": [1, 3, 4, 2],
                "ivc_deg_abdc": 40,
                "evo_deg_bbdc": 45,
                "vvt": {
                    "intake_min_deg": 0,
                    "intake_max_deg": 50,
                    "exhaust_min_deg": 0,
                    "exhaust_max_deg": 30,
                    "k_vvt": 0.06,
                    "g_vvt": g_vvt_grid(50).model_dump(),
                },
                "injection_type": "gdi",
                "throttle_diameter_mm": 56,
                "throttle_location": "post_compressor",
                "intake_manifold_volume_l": 3.0,
                "boost_volume_l": 4.5,
                "exhaust_manifold_volume_l": 0.8,
                "intercooler": {
                    "kind": "air_to_air",
                    "effectiveness": 0.75,
                    "k_dp_kpa_per_kgps2": 120.0,
                },
                "recip_mass_g": 600,
                "true_ve": true_ve_grid(0.98, 4200, 4000, 0.35, 0.30, 60).model_dump(),
                "friction": {"c_bar": 0.25, "a": 0.005, "b_bar_s_m": 0.07, "q_bar_s2_m2": 0.0009},
                "crank_trigger": "60-2",
            },
            turbo={
                "housing": "single_scroll",
                "rotor_inertia_kg_m2": 2.0e-5,
                "bearing_friction_k": 4e-7,
                "turbine_area_eff_cm2": 2.6,
                "turbine_efficiency": Grid1D(
                    x_name="pressure_ratio",
                    x_values=[1.0, 1.5, 2.0, 3.0],
                    values=[0.62, 0.72, 0.75, 0.72],
                ).model_dump(),
                "wastegate_kind": "internal",
                "wastegate_area_max_cm2": 6.0,
                "wastegate_spring_kpa": 50.0,
                "wastegate_full_open_delta_kpa": 8.0,
                "blow_off_valve": True,
                "compressor": {
                    "pr_design": 2.6,
                    "n_design_rpm": 200_000,
                    "n_max_rpm": 220_000,
                    "m_choke_max_kg_s": 0.42,
                    "eta_max": 0.74,
                    "m_peak_kg_s": 0.20,
                    "m_range_kg_s": 0.22,
                    "k1": 0.5,
                    "n_peak_rpm": 170_000,
                },
            },
            injectors={
                "flow_cc_min": 870,
                "dp_ref_kpa": 10_000,
                "rail_pressure_min_kpa": 5000,
                "rail_pressure_max_kpa": 20_000,
                "pressure_reference": "cylinder",
                "dead_time_ms": dead_time_grid(0.35).model_dump(),
            },
            stock_fuel_id="e27",
            allowed_fuel_ids=["e27", "podium", "e0"],
            drive_layout="fwd",
            gear_ratios=[3.46, 2.05, 1.30, 0.92, 0.74, 0.62],
            final_drive_ratio=4.12,
            tire_radius_m=0.316,
            drivetrain_efficiency=0.85,
            driveline_inertia_kg_m2=2.4,
            mechanical_limits={
                "rod_torque_limit_nm": 420,
                "max_rod_load_kn": 52,
                "max_cylinder_pressure_bar": 120,
                "egt_max_c": 950,
                "max_rpm": 6800,
                "rev_limit_rpm": 6500,
                "valve_float_rpm": 7200,
                "turbo_max_rpm": 210_000,
                "max_piston_temp_c": 330,
            },
            rated={
                "peak_power_whp": 220,
                "peak_power_rpm": 6000,
                "peak_torque_nm": 350,
                "peak_torque_rpm_from": 2000,
                "peak_torque_rpm_to": 4500,
                "power_ceiling_whp": 300,
            },
            reference_command_schedule=schedule(
                vid, "e27", HATCH_SCHEDULE, (0.0, 0.0)
            ).model_dump(),
        )
    )


def build_na(hatch: VehicleSpec) -> VehicleSpec:
    """Variante aspirada mínima do hatch (testes de coletor e de aspiração natural)."""
    data = hatch.model_dump()
    data["vehicle_id"] = "test-20-na"
    data["stock_calibration_id"] = "stock-test-20-na-oem-stage"
    data["factory_calibrations"] = _calibration_refs("test-20-na", ["oem-stage"])
    data["induction"] = "natural"
    data["turbo"] = None
    data["engine"]["intercooler"] = None
    data["engine"]["boost_volume_l"] = None
    data["engine"]["injection_type"] = "pfi"
    data["engine"]["compression_ratio"] = 10.5
    data["engine"]["throttle_diameter_mm"] = 60
    data["injectors"] = {
        "flow_cc_min": 550,
        "dp_ref_kpa": 300,
        "rail_pressure_min_kpa": 300,
        "rail_pressure_max_kpa": 300,
        "pressure_reference": "manifold",
        "dead_time_ms": dead_time_grid(1.0).model_dump(),
    }
    data["mechanical_limits"]["turbo_max_rpm"] = None
    data["rated"] = {
        "peak_power_whp": 120,
        "peak_power_rpm": 6000,
        "peak_torque_nm": 190,
        "peak_torque_rpm_from": 4000,
        "peak_torque_rpm_to": 4500,
    }
    rows = [(r, a, lam, 100.0) for r, a, lam, _ in HATCH_SCHEDULE]
    data["reference_command_schedule"] = schedule("test-20-na", "e27", rows).model_dump()
    data["validation_status"] = "draft"
    data["validated_on"] = None
    return VehicleSpec.model_validate(data)


def build_muscle() -> VehicleSpec:
    vid = "muscle-v8-sc"
    rows = _expand(
        [
            (2000, 16.0, 0.90, 150.0),
            (3000, 20.0, 0.85, 158.0),
            (4000, 22.0, 0.82, 162.0),
            (5000, 23.0, 0.80, 165.0),
            (6000, 24.0, 0.79, 165.0),
            (7000, 25.0, 0.79, 160.0),
            (7500, 25.0, 0.79, 158.0),
        ]
    )
    return VehicleSpec.model_validate(
        _base(
            vid,
            display_name="Muscle V8 5,0 sobrealimentado",
            architecture_note="Inspirado em arquitetura V8 5,0 DOHC com compressor volumétrico",
            body="coupe",
            induction="supercharger",
            engine={
                "architecture": "v",
                "n_cyl": 8,
                "v_angle_deg": 90.0,
                "bore_mm": 92.2,
                "stroke_mm": 92.7,
                "rod_length_mm": 150.7,
                "compression_ratio": 9.5,
                "displacement_cc": 4951,
                "valvetrain": "dohc",
                "valves_per_cyl": 4,
                "firing_order": [1, 5, 4, 8, 6, 3, 7, 2],
                "ivc_deg_abdc": 50,
                "evo_deg_bbdc": 50,
                "vvt": {
                    "intake_min_deg": 0,
                    "intake_max_deg": 50,
                    "exhaust_min_deg": 0,
                    "exhaust_max_deg": 50,
                    "k_vvt": 0.06,
                    "g_vvt": g_vvt_grid(50).model_dump(),
                },
                "injection_type": "pfi",
                "throttle_diameter_mm": 87,
                "throttle_location": "pre_compressor",
                "intake_manifold_volume_l": 8.0,
                "boost_volume_l": None,
                "exhaust_manifold_volume_l": 2.0,
                "intercooler": {
                    "kind": "air_to_water",
                    "effectiveness": 0.70,
                    "k_dp_kpa_per_kgps2": 20.0,
                },
                "recip_mass_g": 780,
                "true_ve": true_ve_grid(
                    0.96, 4500, 4500, 0.30, 0.30, 60, [*RPM_AXIS, 7800], MAP_AXIS
                ).model_dump(),
                "crank_trigger": "36-1",
            },
            supercharger={
                "sc_type": "twin_screw",
                "displacement_l_per_rev": 2.65,
                "pulley_ratio": 1.90,
                "k_leak": 0.08,
                "n_ref_rpm": 10_000,
                "adiabatic_efficiency": Grid1D(
                    x_name="pressure_ratio", x_values=[1.0, 2.0, 3.0], values=[0.72, 0.64, 0.58]
                ).model_dump(),
                "mech_efficiency": 0.90,
                "bypass_valve": True,
                "max_rotor_rpm": 18_000,
            },
            injectors={
                "flow_cc_min": 1000,
                "dp_ref_kpa": 400,
                "rail_pressure_min_kpa": 400,
                "rail_pressure_max_kpa": 400,
                "pressure_reference": "manifold",
                "dead_time_ms": dead_time_grid(0.80).model_dump(),
            },
            stock_fuel_id="e27",
            allowed_fuel_ids=["e27", "podium", "e0"],
            drive_layout="rwd",
            gear_ratios=[3.66, 2.43, 1.69, 1.32, 1.00, 0.65],
            final_drive_ratio=3.73,
            tire_radius_m=0.352,
            drivetrain_efficiency=0.85,
            driveline_inertia_kg_m2=3.6,
            mechanical_limits={
                "rod_torque_limit_nm": 1000,
                "max_rod_load_kn": 90,
                "max_cylinder_pressure_bar": 145,
                "egt_max_c": 950,
                "max_rpm": 7800,
                "rev_limit_rpm": 7500,
                "valve_float_rpm": 8000,
                "max_piston_temp_c": 340,
            },
            rated={
                "peak_power_whp": 460,
                "peak_power_rpm": 6500,
                "peak_torque_nm": 650,
                "peak_torque_rpm_from": 4500,
                "peak_torque_rpm_to": 4500,
                "power_ceiling_whp": 800,
            },
            reference_command_schedule=schedule(vid, "e27", rows).model_dump(),
        )
    )


def build_coupe() -> VehicleSpec:
    vid = "coupe-30t-i6"
    rows = _expand(
        [
            (1500, 12.0, 0.98, 170.0),
            (2000, 14.0, 0.95, 195.0),
            (3000, 16.0, 0.90, 205.0),
            (4000, 17.0, 0.86, 210.0),
            (5000, 18.0, 0.82, 215.0),
            (6000, 19.0, 0.80, 205.0),
            (7000, 20.0, 0.80, 190.0),
        ]
    )
    return VehicleSpec.model_validate(
        _base(
            vid,
            display_name="Coupé 3.0 turbo 6 em linha",
            architecture_note="Inspirado em arquitetura 3.0 turbo de 6 cilindros em linha",
            body="coupe",
            induction="turbo",
            engine={
                "architecture": "inline",
                "n_cyl": 6,
                "bore_mm": 82.0,
                "stroke_mm": 94.6,
                "rod_length_mm": 144.4,
                "compression_ratio": 10.2,
                "displacement_cc": 2998,
                "valvetrain": "dohc",
                "valves_per_cyl": 4,
                "firing_order": [1, 5, 3, 6, 2, 4],
                "ivc_deg_abdc": 45,
                "evo_deg_bbdc": 45,
                "vvt": {
                    "intake_min_deg": 0,
                    "intake_max_deg": 70,
                    "exhaust_min_deg": 0,
                    "exhaust_max_deg": 55,
                    "k_vvt": 0.06,
                    "g_vvt": g_vvt_grid(70).model_dump(),
                },
                "injection_type": "gdi",
                "throttle_diameter_mm": 68,
                "intake_manifold_volume_l": 4.0,
                "boost_volume_l": 3.0,
                "exhaust_manifold_volume_l": 1.2,
                "intercooler": {
                    "kind": "air_to_water",
                    "effectiveness": 0.80,
                    "k_dp_kpa_per_kgps2": 60.0,
                },
                "recip_mass_g": 610,
                "true_ve": true_ve_grid(
                    1.00, 4500, 4500, 0.30, 0.30, 60, [*RPM_AXIS, 7200]
                ).model_dump(),
            },
            turbo={
                "housing": "twin_scroll",
                "rotor_inertia_kg_m2": 3.5e-5,
                "bearing_friction_k": 5e-7,
                "turbine_area_eff_cm2": 11.0,
                "turbine_efficiency": Grid1D(
                    x_name="pressure_ratio",
                    x_values=[1.0, 1.5, 2.0, 3.0],
                    values=[0.55, 0.70, 0.74, 0.72],
                ).model_dump(),
                "wastegate_kind": "internal",
                "wastegate_area_max_cm2": 4.5,
                "wastegate_spring_kpa": 60.0,
                "compressor": {
                    "pr_design": 2.4,
                    "n_design_rpm": 170_000,
                    "n_max_rpm": 190_000,
                    "m_choke_max_kg_s": 0.38,
                    "eta_max": 0.76,
                    "m_peak_kg_s": 0.24,
                    "m_range_kg_s": 0.16,
                    "n_peak_rpm": 150_000,
                },
            },
            injectors={
                "flow_cc_min": 1100,
                "dp_ref_kpa": 10_000,
                "rail_pressure_min_kpa": 5000,
                "rail_pressure_max_kpa": 20_000,
                "pressure_reference": "cylinder",
                "dead_time_ms": dead_time_grid(0.35).model_dump(),
            },
            stock_fuel_id="e27",
            allowed_fuel_ids=["e27", "podium", "e0"],
            drive_layout="rwd",
            gear_ratios=[5.00, 3.20, 2.14, 1.72, 1.31, 1.00, 0.82, 0.64],
            final_drive_ratio=3.15,
            tire_radius_m=0.333,
            drivetrain_efficiency=0.85,
            driveline_inertia_kg_m2=3.2,
            mechanical_limits={
                "rod_torque_limit_nm": 1000,
                "max_rod_load_kn": 95,
                "max_cylinder_pressure_bar": 160,
                "egt_max_c": 980,
                "max_rpm": 7200,
                "rev_limit_rpm": 7000,
                "valve_float_rpm": 7600,
                "turbo_max_rpm": 180_000,
                "max_piston_temp_c": 360,
            },
            rated={
                "peak_power_whp": 340,
                "peak_power_rpm": 6000,
                "peak_torque_nm": 500,
                "peak_torque_rpm_from": 2000,
                "peak_torque_rpm_to": 5000,
                "power_ceiling_whp": 750,
            },
            reference_command_schedule=schedule(vid, "e27", rows).model_dump(),
        )
    )


def build_classic() -> VehicleSpec:
    vid = "classic-20t-swap"
    rows = _expand(
        [
            (3000, 18.0, 0.82, 170.0),
            (4000, 20.0, 0.80, 210.0),
            (5000, 22.0, 0.78, 225.0),
            (6000, 23.0, 0.78, 230.0),
            (7000, 24.0, 0.78, 225.0),
            (7500, 24.0, 0.78, 220.0),
        ]
    )
    return VehicleSpec.model_validate(
        _base(
            vid,
            display_name="Clássico 2.0 turbo de swap",
            architecture_note="Inspirado em arquitetura 2.0 8v de 4 cilindros turbo forjado",
            induction="turbo",
            stock_fuel_id="e100",
            allowed_fuel_ids=["e100", "e27", "podium"],
            reference_curve_ids=["stock-e100"],
            factory_calibrations=_calibration_refs(vid, ["oem-stage", "ft-pro"]),
            engine={
                "architecture": "inline",
                "n_cyl": 4,
                "bore_mm": 82.5,
                "stroke_mm": 92.8,
                "rod_length_mm": 144.0,
                "compression_ratio": 8.5,
                "displacement_cc": 1984,
                "valvetrain": "sohc",
                "valves_per_cyl": 2,
                "firing_order": [1, 3, 4, 2],
                "ivc_deg_abdc": 38,
                "evo_deg_bbdc": 40,
                "vvt": None,
                "injection_type": "pfi",
                "throttle_diameter_mm": 60,
                "intake_manifold_volume_l": 3.5,
                "boost_volume_l": 6.0,
                "exhaust_manifold_volume_l": 1.5,
                "intercooler": {
                    "kind": "air_to_air",
                    "effectiveness": 0.72,
                    "k_dp_kpa_per_kgps2": 60.0,
                },
                "recip_mass_g": 640,
                "true_ve": true_ve_grid(
                    0.90, 5000, 4500, 0.40, 0.25, 70, [*RPM_AXIS, 7800], [*MAP_AXIS, 300]
                ).model_dump(),
            },
            turbo={
                "housing": "single_scroll",
                "compressor_ar": 0.50,
                "turbine_ar": 0.63,
                "rotor_inertia_kg_m2": 4.5e-5,
                "bearing_friction_k": 6e-7,
                "turbine_area_eff_cm2": 13.0,
                "turbine_efficiency": Grid1D(
                    x_name="pressure_ratio",
                    x_values=[1.0, 1.5, 2.0, 3.0],
                    values=[0.55, 0.68, 0.72, 0.70],
                ).model_dump(),
                "wastegate_kind": "external",
                "wastegate_area_max_cm2": 11.3,
                "wastegate_spring_kpa": 90.0,
                "compressor": {
                    "pr_design": 3.2,
                    "n_design_rpm": 140_000,
                    "n_max_rpm": 155_000,
                    "m_choke_max_kg_s": 0.55,
                    "eta_max": 0.75,
                    "m_peak_kg_s": 0.38,
                    "m_range_kg_s": 0.22,
                    "n_peak_rpm": 120_000,
                },
            },
            injectors={
                "flow_cc_min": 2000,
                "dp_ref_kpa": 300,
                "rail_pressure_min_kpa": 300,
                "rail_pressure_max_kpa": 300,
                "pressure_reference": "manifold",
                "dead_time_ms": dead_time_grid(1.0).model_dump(),
            },
            drive_layout="fwd",
            gear_ratios=[3.45, 1.94, 1.29, 0.97, 0.80],
            final_drive_ratio=3.89,
            tire_radius_m=0.300,
            drivetrain_efficiency=0.88,
            driveline_inertia_kg_m2=2.0,
            mechanical_limits={
                "rod_torque_limit_nm": 720,
                "max_rod_load_kn": 70,
                "max_cylinder_pressure_bar": 140,
                "egt_max_c": 950,
                "max_rpm": 7800,
                "rev_limit_rpm": 7500,
                "valve_float_rpm": 8200,
                "turbo_max_rpm": 150_000,
                "max_piston_temp_c": 350,
            },
            rated={
                "peak_power_whp": 319,
                "peak_power_rpm": 6500,
                "peak_torque_nm": 450,
                "peak_torque_rpm_from": 5000,
                "peak_torque_rpm_to": 5000,
                "power_range_whp": (300, 600),
                "power_ceiling_whp": 600,
            },
            reference_command_schedule=schedule(vid, "e100", rows).model_dump(),
        )
    )


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="session")
def fuels() -> dict[str, FuelSpec]:
    return dict(FUELS)


@pytest.fixture(scope="session")
def hatch() -> VehicleSpec:
    return build_hatch()


@pytest.fixture(scope="session")
def na_vehicle(hatch: VehicleSpec) -> VehicleSpec:
    return build_na(hatch)


@pytest.fixture(scope="session")
def muscle() -> VehicleSpec:
    return build_muscle()


@pytest.fixture(scope="session")
def coupe() -> VehicleSpec:
    return build_coupe()


@pytest.fixture(scope="session")
def classic() -> VehicleSpec:
    return build_classic()


@pytest.fixture(scope="session")
def vehicles(
    hatch: VehicleSpec, coupe: VehicleSpec, classic: VehicleSpec, muscle: VehicleSpec
) -> dict[str, VehicleSpec]:
    return {v.vehicle_id: v for v in (hatch, coupe, classic, muscle)}


@pytest.fixture(scope="session")
def hatch_schedule(hatch: VehicleSpec) -> ReferenceCommandSchedule:
    return hatch.reference_command_schedule


EngineFactory = Callable[..., PhysicsEngine]


@pytest.fixture
def make_engine(fuels: dict[str, FuelSpec]) -> EngineFactory:
    """``make_engine(vehicle, fuel_id=None, warm=True, **config)`` → ``PhysicsEngine``."""

    def factory(
        vehicle: VehicleSpec, fuel_id: str | None = None, *, warm: bool = True, **config: Any
    ) -> PhysicsEngine:
        fuel = fuels[fuel_id or vehicle.stock_fuel_id]
        cfg = PhysicsConfig(**config)
        return PhysicsEngine(cfg, vehicle, fuel, initial_ect_c=90.0 if warm else None)

    return factory


@dataclass
class SteadyResult:
    rpm: float
    torque_nm: float
    whp: float
    wheel_kw: float
    power_kw: float
    lambda_collector: float
    egt_collector_c: float
    map_kpa: float
    theta_pmax: float
    last: EngineState


def run_steady_impl(
    engine: PhysicsEngine,
    driver: ReferenceDriver,
    rpm: float,
    seconds: float = 3.0,
    avg_s: float = 0.3,
) -> SteadyResult:
    """Segura ``rpm`` com o banco PI e devolve médias do último ``avg_s``."""
    dt = engine.resolved.dt
    rig = RpmHoldRig(target_rpm=rpm)
    if engine.rpm < 1.0:
        engine.crank(rpm)
    else:
        engine.crank(rpm)
    state: EngineState | None = None
    n = round(seconds / dt)
    n_avg = max(1, round(avg_s / dt))
    acc = [0.0] * 8
    for k in range(n):
        sensors = engine.read_sensors()
        cmd = driver.commands(sensors, dt)
        load = rig.load(state, engine.rpm, dt)
        state = engine.step(cmd, load, dt)
        if k >= n - n_avg:
            acc[0] += state.torque_nm
            acc[1] += state.whp
            acc[2] += state.wheel_power_kw
            acc[3] += state.power_kw
            acc[4] += state.lambda_collector or 0.0
            acc[5] += state.egt_collector_c
            acc[6] += state.map_kpa
            acc[7] += sum(state.theta_pmax_deg_atdc) / len(state.theta_pmax_deg_atdc)
    assert state is not None
    avg = [a / n_avg for a in acc]
    return SteadyResult(rpm, avg[0], avg[1], avg[2], avg[3], avg[4], avg[5], avg[6], avg[7], state)


@pytest.fixture
def run_steady() -> Callable[..., SteadyResult]:
    return run_steady_impl


@pytest.fixture
def sweep(make_engine: EngineFactory) -> Callable[..., list[SteadyResult]]:
    """Varredura a plena carga em regime permanente (passo configurável)."""

    def run(
        vehicle: VehicleSpec,
        rpms: list[float],
        seconds: float = 3.0,
        sim_hz: int = 500,
        **driver_kw: Any,
    ) -> list[SteadyResult]:
        engine = make_engine(vehicle, sim_hz=sim_hz, noise_enabled=False)
        driver = ReferenceDriver(engine, vehicle.reference_command_schedule, **driver_kw)
        return [run_steady_impl(engine, driver, r, seconds) for r in rpms]

    return run
