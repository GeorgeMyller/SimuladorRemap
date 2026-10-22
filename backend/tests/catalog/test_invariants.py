"""Invariantes dos 4 veículos do pacote (RF-02 a RF-04, RF-08 a RF-10, RF-26, RF-28; A.2/A.3).

Os testes de contrato isolados (modelos sintéticos) ficam em ``test_contracts.py``; aqui
verificam-se os valores dos arquivos de dados contra os Apêndices A.2 e A.3 da spec.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from simremap.catalog.loader import Catalog

# A.3: biela, carga, pressão, EGT, corte / máx / flutuação, turbo, pistão. O turbo do hatch
# passou de 210 000 para 250 000 rpm na recalibração gain-calibration (turbo classe IS20).
LIMITS: dict[str, tuple[float | None, ...]] = {
    "hatch-20t-gdi": (420, 52, 120, 950, 6500, 6800, 7200, 250_000, 330),
    "coupe-30t-i6": (1000, 95, 160, 980, 7000, 7200, 7600, 180_000, 360),
    "classic-20t-swap": (720, 70, 140, 950, 7500, 7800, 8200, 150_000, 350),
    "muscle-v8-sc": (1000, 90, 145, 950, 7500, 7800, 8000, None, 340),
}
GEOMETRY = {  # A.2: diâmetro, curso, biela, cilindrada calculada, ordem de ignição
    "hatch-20t-gdi": (82.5, 92.8, 144.0, 1984.3, [1, 3, 4, 2]),
    "coupe-30t-i6": (82.0, 94.6, 144.4, 2997.5, [1, 5, 3, 6, 2, 4]),
    "classic-20t-swap": (82.5, 92.8, 144.0, 1984.3, [1, 3, 4, 2]),
    "muscle-v8-sc": (92.2, 92.7, 150.7, 4951.3, [1, 5, 4, 8, 6, 3, 7, 2]),
}
TRANSMISSION = {  # A.2: tração, marchas, diferencial, raio, η, inércia
    "hatch-20t-gdi": ("fwd", [3.46, 2.05, 1.30, 0.92, 0.74, 0.62], 4.12, 0.316, 0.85, 2.4),
    "coupe-30t-i6": (
        "rwd",
        [5.00, 3.20, 2.14, 1.72, 1.31, 1.00, 0.82, 0.64],
        3.15,
        0.333,
        0.85,
        3.2,
    ),
    "classic-20t-swap": ("fwd", [3.45, 1.94, 1.29, 0.97, 0.80], 3.89, 0.300, 0.88, 2.0),
    "muscle-v8-sc": ("rwd", [3.66, 2.43, 1.69, 1.32, 1.00, 0.65], 3.73, 0.352, 0.85, 3.6),
}
FUELS = {
    "hatch-20t-gdi": ("e27", ["e27", "podium", "e0"]),
    "coupe-30t-i6": ("e27", ["e27", "podium", "e0"]),
    "classic-20t-swap": ("e100", ["e100", "e27", "podium"]),
    "muscle-v8-sc": ("e27", ["e27", "podium", "e0"]),
}
VIDS = list(LIMITS)


@pytest.mark.parametrize("vid", VIDS)
def test_geometry_and_firing_order(real_catalog: Catalog, vid: str) -> None:
    eng = real_catalog.vehicles[vid].spec.engine
    bore, stroke, rod, calc, order = GEOMETRY[vid]
    assert (eng.bore_mm, eng.stroke_mm, eng.rod_length_mm) == (bore, stroke, rod)
    assert eng.calc_displacement_cc == pytest.approx(calc, abs=0.05)
    assert abs(eng.displacement_cc - eng.calc_displacement_cc) <= 0.005 * eng.calc_displacement_cc
    assert 2.8 <= eng.rod_length_mm / (eng.stroke_mm / 2) <= 4.2
    assert eng.firing_order == order


@pytest.mark.parametrize("vid", VIDS)
def test_mechanical_limits(real_catalog: Catalog, vid: str) -> None:
    spec = real_catalog.vehicles[vid].spec
    lim = spec.mechanical_limits
    got = (lim.rod_torque_limit_nm, lim.max_rod_load_kn, lim.max_cylinder_pressure_bar,
           lim.egt_max_c, lim.rev_limit_rpm, lim.max_rpm, lim.valve_float_rpm, lim.turbo_max_rpm,
           lim.max_piston_temp_c)  # fmt: skip
    assert got == LIMITS[vid]
    assert lim.rev_limit_rpm <= lim.max_rpm < lim.valve_float_rpm
    assert lim.rod_torque_limit_nm > spec.rated.peak_torque_nm
    assert (lim.turbo_max_rpm is not None) == (spec.induction == "turbo")


@pytest.mark.parametrize("vid", VIDS)
def test_transmission_and_fuels(real_catalog: Catalog, vid: str) -> None:
    spec = real_catalog.vehicles[vid].spec
    drive, gears, final, tire, eta, inertia = TRANSMISSION[vid]
    assert (spec.drive_layout, spec.gear_ratios, spec.final_drive_ratio) == (drive, gears, final)
    assert (spec.tire_radius_m, spec.drivetrain_efficiency) == (tire, eta)
    assert (spec.driveline_inertia_kg_m2, spec.drivetrain_fixed_loss_kw) == (inertia, 0.0)
    assert (spec.stock_fuel_id, spec.allowed_fuel_ids) == FUELS[vid]
    # T267/T403-T405: validados pela varredura física contra o benchmark v1
    assert spec.validation_status == "validated"
    assert spec.validated_on is not None
    assert spec.stock_calibration_id == f"stock-{vid}-oem-stage"


def test_induction(real_catalog: Catalog) -> None:
    v = {vid: e.spec for vid, e in real_catalog.vehicles.items()}
    hatch_turbo = v["hatch-20t-gdi"].turbo
    classic_turbo = v["classic-20t-swap"].turbo
    coupe_turbo = v["coupe-30t-i6"].turbo
    assert hatch_turbo is not None and classic_turbo is not None and coupe_turbo is not None
    assert hatch_turbo.housing == "single_scroll" and hatch_turbo.wastegate_kind == "internal"
    # gain-calibration (classe IS20): turbina 3,2 cm², wastegate 6 cm², compressor PR 2,9 a
    # 200 000 rpm, choke 0,488 kg/s a 250 000 rpm e ilha de η 0,77 em 0,24 kg/s
    assert (hatch_turbo.compressor.pr_design, hatch_turbo.compressor.n_max_rpm) == (2.9, 250_000)
    assert (hatch_turbo.turbine_area_eff_cm2, hatch_turbo.wastegate_area_max_cm2) == (3.2, 6.0)
    assert hatch_turbo.compressor.m_choke_max_kg_s == 0.488
    assert (hatch_turbo.compressor.eta_max, hatch_turbo.compressor.m_peak_kg_s) == (0.77, 0.24)
    assert coupe_turbo.housing == "twin_scroll"
    assert classic_turbo.wastegate_kind == "external"
    assert classic_turbo.wastegate_area_max_cm2 == 11.3
    sc = v["muscle-v8-sc"].supercharger
    assert sc is not None and v["muscle-v8-sc"].turbo is None
    # afinação T405: polia 2,10 (A.3: 1,90) e k_leak 0,20 para a curva v1
    assert (sc.sc_type, sc.displacement_l_per_rev, sc.pulley_ratio) == ("twin_screw", 2.65, 2.10)
    assert sc.k_leak == 0.20
    assert sc.max_rotor_rpm == 18_000
    assert sc.adiabatic_efficiency.values[0] == 0.74 and sc.adiabatic_efficiency.values[-1] == 0.65
    assert v["muscle-v8-sc"].engine.throttle_location == "pre_compressor"
    assert v["muscle-v8-sc"].engine.boost_volume_l is None
    assert v["muscle-v8-sc"].engine.architecture == "v"
    assert v["muscle-v8-sc"].engine.v_angle_deg == 90.0


def test_injectors_and_valvetrain(real_catalog: Catalog) -> None:
    v = {vid: e.spec for vid, e in real_catalog.vehicles.items()}
    expected = {
        "hatch-20t-gdi": (870, 10_000, "cylinder", "gdi", 4, "dohc", "60-2"),
        "coupe-30t-i6": (1100, 10_000, "cylinder", "gdi", 4, "dohc", "60-2"),
        "classic-20t-swap": (2000, 300, "manifold", "pfi", 2, "sohc", "60-2"),
        "muscle-v8-sc": (1000, 400, "manifold", "pfi", 4, "dohc", "36-1"),
    }
    for vid, (flow, dp, ref, inj, valves, cam, trigger) in expected.items():
        spec = v[vid]
        assert (spec.injectors.flow_cc_min, spec.injectors.dp_ref_kpa) == (flow, dp)
        assert spec.injectors.pressure_reference == ref
        assert (spec.engine.injection_type, spec.engine.valves_per_cyl) == (inj, valves)
        assert (spec.engine.valvetrain, spec.engine.crank_trigger) == (cam, trigger)
    assert v["classic-20t-swap"].engine.vvt is None  # OQ-04: 8v sem VVT


@pytest.mark.parametrize("vid", VIDS)
def test_grids(real_catalog: Catalog, vid: str) -> None:
    eng = real_catalog.vehicles[vid].spec.engine
    ve = eng.true_ve
    assert len(ve.x_values) == len(ve.y_values) == 16
    assert ve.x_values[-1] == max(7000.0, real_catalog.vehicles[vid].spec.mechanical_limits.max_rpm)
    assert ve.y_values[-1] == (300.0 if vid == "classic-20t-swap" else 260.0)
    for row in ve.z_values:
        assert all(0.20 <= value <= 1.35 and math.isfinite(value) for value in row)
    assert eng.mbt_reference is not None
    assert (len(eng.mbt_reference.x_values), len(eng.mbt_reference.y_values)) == (16, 16)
    if eng.vvt is not None:
        assert all(-1.0 <= g <= 1.0 for row in eng.vvt.g_vvt.z_values for g in row)


def test_ve_formula_a7(real_catalog: Catalog) -> None:
    ve = real_catalog.vehicles["hatch-20t-gdi"].spec.engine.true_ve
    j = ve.x_values.index(4000.0)
    i = ve.y_values.index(100.0)
    expected = 0.98 * (1 - 0.35 * ((4000 - 4200) / 4000) ** 2) * (1 - 0.30 * math.exp(-100 / 60))
    assert ve.z_values[i][j] == pytest.approx(expected, abs=5e-5)


def test_physics_does_not_read_mbt_reference() -> None:
    """RF-26: ``mbt_reference`` é só para a UI."""
    physics = Path(__file__).resolve().parents[2] / "src" / "simremap" / "physics"
    offenders = [p.name for p in physics.rglob("*.py") if "mbt_reference" in p.read_text("utf-8")]
    assert offenders == []
