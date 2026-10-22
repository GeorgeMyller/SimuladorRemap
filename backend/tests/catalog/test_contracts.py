"""Contratos do catálogo (T024, T025; catalog RF-02 a RF-04, RF-08, RF-09, RF-11, RF-12,
RF-19, RF-21, RF-28)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from simremap.catalog.contracts import (
    BENCHMARK_ID,
    EngineSpec,
    FactoryCalibrationRef,
    FuelSpec,
    Grid1D,
    Grid2D,
    MechanicalLimits,
    Provenance,
    ReferenceCommandSchedule,
    ReferenceCurve,
    ReferenceCurveListResponse,
    ReferenceCurvePoint,
    VehicleDetail,
    VehicleSpec,
)

SHA = "a" * 64


def grid2d(x_name: str = "rpm", y_name: str = "map_kpa", value: float = 0.9) -> dict[str, Any]:
    return {
        "x_name": x_name,
        "x_values": [1000.0, 4000.0, 7000.0],
        "y_name": y_name,
        "y_values": [30.0, 100.0, 250.0],
        "z_values": [[value] * 3 for _ in range(3)],
    }


def engine(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "architecture": "inline",
        "n_cyl": 4,
        "bore_mm": 82.5,
        "stroke_mm": 92.8,
        "rod_length_mm": 144.0,
        "compression_ratio": 9.6,
        "displacement_cc": 1984.0,
        "valvetrain": "dohc",
        "valves_per_cyl": 4,
        "firing_order": [1, 3, 4, 2],
        "ivc_deg_abdc": 40.0,
        "evo_deg_bbdc": 45.0,
        "injection_type": "gdi",
        "throttle_diameter_mm": 56.0,
        "intake_manifold_volume_l": 2.5,
        "boost_volume_l": 3.0,
        "exhaust_manifold_volume_l": 1.0,
        "recip_mass_g": 600.0,
        "true_ve": grid2d(),
    }
    data.update(over)
    return data


def limits(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "rod_torque_limit_nm": 420.0,
        "max_rod_load_kn": 52.0,
        "max_cylinder_pressure_bar": 120.0,
        "egt_max_c": 950.0,
        "max_rpm": 6800.0,
        "rev_limit_rpm": 6500.0,
        "valve_float_rpm": 7200.0,
        "turbo_max_rpm": 220000.0,
        "max_piston_temp_c": 330.0,
    }
    data.update(over)
    return data


def turbo() -> dict[str, Any]:
    return {
        "housing": "single_scroll",
        "rotor_inertia_kg_m2": 2e-5,
        "bearing_friction_k": 1e-8,
        "turbine_area_eff_cm2": 8.0,
        "turbine_efficiency": {
            "x_name": "pressure_ratio",
            "x_values": [1.0, 2.0, 3.0],
            "values": [0.6, 0.7, 0.65],
        },
        "wastegate_kind": "internal",
        "wastegate_area_max_cm2": 3.0,
        "wastegate_spring_kpa": 60.0,
        "compressor": {
            "pr_design": 2.5,
            "n_design_rpm": 180000,
            "n_max_rpm": 230000,
            "m_choke_max_kg_s": 0.25,
            "eta_max": 0.76,
            "m_peak_kg_s": 0.15,
            "m_range_kg_s": 0.1,
            "n_peak_rpm": 150000,
        },
    }


def schedule(vehicle_id: str = "hatch-20t-gdi", n: int = 19) -> dict[str, Any]:
    return {
        "vehicle_id": vehicle_id,
        "fuel_id": "e27",
        "points": [
            {
                "rpm": 2000.0 + 250.0 * i,
                "ignition_advance_deg": 10.0,
                "lambda_target": 0.82,
                "map_target_kpa": 220.0,
            }
            for i in range(n)
        ],
    }


def vehicle(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "vehicle_id": "hatch-20t-gdi",
        "display_name": "Hatch 2.0 turbo GDI",
        "architecture_note": "4 cilindros em linha, turbo, injeção direta",
        "body": "hatch",
        "data_version": 1,
        "validation_status": "validated",
        "validated_on": "2026-10-01",
        "induction": "turbo",
        "engine": engine(),
        "turbo": turbo(),
        "injectors": {
            "flow_cc_min": 900.0,
            "dp_ref_kpa": 10000.0,
            "rail_pressure_min_kpa": 5000.0,
            "rail_pressure_max_kpa": 20000.0,
            "pressure_reference": "cylinder",
            "dead_time_ms": grid2d("battery_v", "dp_kpa", 0.5)
            | {"x_values": [8.0, 12.0, 16.0], "y_values": [5000.0, 10000.0, 20000.0]},
        },
        "stock_fuel_id": "e27",
        "allowed_fuel_ids": ["e27", "e100", "podium"],
        "drive_layout": "fwd",
        "gear_ratios": [3.5, 2.1, 1.4, 1.0, 0.8, 0.65],
        "final_drive_ratio": 3.9,
        "tire_radius_m": 0.31,
        "drivetrain_efficiency": 0.85,
        "driveline_inertia_kg_m2": 2.0,
        "mechanical_limits": limits(),
        "rated": {
            "peak_power_whp": 200.0,
            "peak_power_rpm": 5500.0,
            "peak_torque_nm": 350.0,
            "peak_torque_rpm_from": 1800.0,
            "peak_torque_rpm_to": 4500.0,
        },
        "stock_profile_id": "oem-stage",
        "stock_calibration_id": "stock-hatch-20t-gdi-oem-stage",
        "factory_calibrations": [
            {
                "profile_id": "oem-stage",
                "calibration_id": "stock-hatch-20t-gdi-oem-stage",
                "file": "calibrations/oem-stage.json",
                "sha256": SHA,
            }
        ],
        "reference_command_schedule": schedule(),
        "reference_curve_ids": ["stock-e27"],
    }
    data.update(over)
    return data


def fuel(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "fuel_id": "e100",
        "display_name": "Etanol hidratado",
        "afr_stoich": 9.0,
        "lhv_mj_kg": 26.8,
        "ron": 110.0,
        "mon": 92.0,
        "knock_on": 105.0,
        "h_fg_kj_kg": 920.0,
        "density_kg_m3": 789.0,
        "ethanol_mass_fraction": 0.93,
        "laminar_bm_m_s": 0.465,
        "laminar_bphi_m_s": -2.0,
        "laminar_phi_m": 1.1,
        "preignition_surface_temp_c": 840.0,
    }
    data.update(over)
    return data


def curve(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "curve_id": "stock-e27",
        "vehicle_id": "hatch-20t-gdi",
        "fuel_id": "e27",
        "quantities": ["torque_crank_nm", "power_wheel_kw"],
        "points": [
            {"rpm": 2000.0 + 250 * i, "torque_crank_nm": 340.0, "power_wheel_kw": 60.0 + i}
            for i in range(19)
        ],
        "source": "estimativa interna",
        "license": "internal-estimate",
        "confidence": "estimated",
    }
    data.update(over)
    return data


class TestGrids:
    def test_grid2d_valid(self) -> None:
        assert Grid2D.model_validate(grid2d()).z_values[0][0] == 0.9

    @pytest.mark.parametrize(
        "over",
        [
            {"x_values": [1000.0, 1000.0, 2000.0]},
            {"y_values": [30.0, 20.0, 250.0]},
            {"z_values": [[1.0, 1.0, 1.0]]},
            {"z_values": [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]},
            {"z_values": [[float("nan")] * 3] * 3},
        ],
    )
    def test_grid2d_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            Grid2D.model_validate(grid2d() | over)

    def test_grid1d(self) -> None:
        Grid1D(x_name="pressure_ratio", x_values=[1.0, 2.0], values=[0.5, 0.6])
        with pytest.raises(ValidationError):
            Grid1D(x_name="pressure_ratio", x_values=[1.0, 2.0], values=[0.5])
        with pytest.raises(ValidationError):
            Grid1D(x_name="pressure_ratio", x_values=[2.0, 1.0], values=[0.5, 0.6])
        with pytest.raises(ValidationError):
            Grid1D(x_name="pressure_ratio", x_values=[1.0, float("inf")], values=[0.5, 0.6])


class TestEngineSpec:
    def test_hatch_geometry(self) -> None:
        spec = EngineSpec.model_validate(engine())
        assert spec.calc_displacement_cc == pytest.approx(1984.3, abs=0.1)
        dumped = spec.model_dump()
        assert "calc_displacement_cc" in dumped
        assert EngineSpec.model_validate(dumped) == spec

    @pytest.mark.parametrize(
        ("over", "match"),
        [
            ({"displacement_cc": 2100.0}, "0,5 %"),
            ({"rod_length_mm": 200.0}, "biela"),
            ({"rod_length_mm": 120.0}, "biela"),
            ({"firing_order": [1, 3, 3, 2]}, "permutação"),
            ({"firing_order": [3, 1, 4, 2]}, "começar no cilindro 1"),
            ({"architecture": "v"}, "v_angle_deg"),
            ({"v_angle_deg": 90.0}, "v_angle_deg"),
            ({"true_ve": grid2d(value=1.5)}, "true_ve"),
        ],
    )
    def test_rejections(self, over: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            EngineSpec.model_validate(engine(**over))

    def test_v8_firing_order(self) -> None:
        v8 = engine(
            architecture="v",
            v_angle_deg=90.0,
            n_cyl=8,
            bore_mm=103.25,
            stroke_mm=92.0,
            rod_length_mm=154.0,
            displacement_cc=6162.0,
            firing_order=[1, 5, 4, 8, 6, 3, 7, 2],
        )
        assert EngineSpec.model_validate(v8).n_cyl == 8


class TestMechanicalLimits:
    def test_structural_limits_required(self) -> None:
        lim = MechanicalLimits.model_validate(limits())
        assert (lim.max_rod_load_kn, lim.max_cylinder_pressure_bar) == (52.0, 120.0)
        assert (lim.max_piston_temp_c, lim.valve_float_rpm) == (330.0, 7200.0)
        assert lim.egt_limit_c == lim.egt_max_c
        for name in (
            "max_rod_load_kn",
            "max_cylinder_pressure_bar",
            "max_piston_temp_c",
            "valve_float_rpm",
        ):
            data = limits()
            del data[name]
            with pytest.raises(ValidationError, match=name):
                MechanicalLimits.model_validate(data)

    @pytest.mark.parametrize(
        "over",
        [{"rev_limit_rpm": 7000.0}, {"valve_float_rpm": 6800.0}, {"max_rod_load_kn": 5.0}],
    )
    def test_invariants(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            MechanicalLimits.model_validate(limits(**over))


class TestFuelSpec:
    def test_density_g_cc(self) -> None:
        spec = FuelSpec.model_validate(fuel())
        assert spec.density_g_cc == pytest.approx(0.789)
        assert FuelSpec.model_validate_json(spec.model_dump_json()) == spec

    def test_unknown_fuel(self) -> None:
        with pytest.raises(ValidationError):
            FuelSpec.model_validate(fuel(fuel_id="e85"))

    def test_provenance_source(self) -> None:
        Provenance(kind="estimate")  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="source"):
            Provenance(kind="literature")  # type: ignore[arg-type]


class TestVehicleSpec:
    def test_valid_round_trip(self) -> None:
        spec = VehicleSpec.model_validate(vehicle())
        assert spec.factory_calibration("oem-stage") is not None
        assert spec.factory_calibration("ft-pro") is None
        assert VehicleSpec.model_validate_json(spec.model_dump_json()) == spec

    def test_strip_whitespace(self) -> None:
        spec = VehicleSpec.model_validate(vehicle(display_name="  Hatch 2.0  "))
        assert spec.display_name == "Hatch 2.0"

    @pytest.mark.parametrize(
        ("over", "match"),
        [
            ({"supercharger": {"x": 1}}, "supercharger"),
            ({"turbo": None}, "turbo"),
            ({"mechanical_limits": limits(turbo_max_rpm=None)}, "turbo_max_rpm"),
            ({"stock_fuel_id": "e0"}, "allowed_fuel_ids"),
            ({"stock_calibration_id": "stock-x-oem-stage"}, "stock_calibration_id"),
            ({"validated_on": None}, "validated_on"),
            ({"gear_ratios": [3.5, 3.6, 1.4, 1.0]}, "decrescente"),
            ({"mechanical_limits": limits(rod_torque_limit_nm=340.0)}, "torque de pico"),
            ({"reference_command_schedule": schedule("coupe-30t-i6")}, "vehicle_id"),
            ({"vehicle_id": "Hatch"}, "pattern"),
            ({"engine": engine(throttle_location="pre_compressor")}, "pre_compressor"),
        ],
    )
    def test_rejections(self, over: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            VehicleSpec.model_validate(vehicle(**over))

    def test_supercharger_vehicle(self) -> None:
        data = vehicle(
            vehicle_id="muscle-v8-sc",
            induction="supercharger",
            turbo=None,
            supercharger={
                "sc_type": "roots",
                "displacement_l_per_rev": 1.9,
                "pulley_ratio": 2.4,
                "adiabatic_efficiency": {
                    "x_name": "pressure_ratio",
                    "x_values": [1.0, 2.0],
                    "values": [0.6, 0.55],
                },
                "max_rotor_rpm": 16000,
            },
            mechanical_limits=limits(turbo_max_rpm=None),
            stock_calibration_id="stock-muscle-v8-sc-oem-stage",
            factory_calibrations=[
                {
                    "profile_id": "oem-stage",
                    "calibration_id": "stock-muscle-v8-sc-oem-stage",
                    "file": "calibrations/oem-stage.json",
                    "sha256": SHA,
                }
            ],
            reference_command_schedule=schedule("muscle-v8-sc"),
            engine=engine(throttle_location="pre_compressor", boost_volume_l=None),
        )
        assert VehicleSpec.model_validate(data).induction == "supercharger"

    def test_detail_extends_spec(self) -> None:
        detail = VehicleDetail.model_validate(
            vehicle()
            | {
                "estimated_fields": ["/engine/true_ve"],
                "data_sha256": SHA,
                "catalog_version": "1.0.0",
                "fuels": [fuel()],
            }
        )
        assert VehicleDetail.model_validate_json(detail.model_dump_json()) == detail


class TestReferenceData:
    def test_factory_ref(self) -> None:
        ref = FactoryCalibrationRef(
            profile_id="ft-pro",
            calibration_id="stock-hatch-20t-gdi-ft-pro",
            file="calibrations/ft-pro.json",
            sha256=SHA,
        )
        assert ref.profile_id == "ft-pro"
        with pytest.raises(ValidationError):
            FactoryCalibrationRef(
                profile_id="ft-pro",
                calibration_id="stock-hatch-20t-gdi-oem-stage",
                file="calibrations/ft-pro.json",
                sha256=SHA,
            )
        with pytest.raises(ValidationError):
            FactoryCalibrationRef(
                profile_id="ft-pro",
                calibration_id="stock-hatch-20t-gdi-ft-pro",
                file="calibrations/ft-pro.json",
                sha256="X" * 64,
            )

    def test_schedule(self) -> None:
        assert len(ReferenceCommandSchedule.model_validate(schedule()).points) == 19
        bad = schedule()
        bad["points"][3]["rpm"] += 50
        with pytest.raises(ValidationError, match="250"):
            ReferenceCommandSchedule.model_validate(bad)
        with pytest.raises(ValidationError):
            ReferenceCommandSchedule.model_validate(schedule(n=7))

    def test_curve_valid(self) -> None:
        c = ReferenceCurve.model_validate(curve())
        assert c.benchmark_id == BENCHMARK_ID
        assert c.tolerance_pct == 5.0
        assert c.covers_rev_limit(6500.0)
        assert not c.covers_rev_limit(7000.0)
        assert c.points[0].power_wheel_whp == pytest.approx(60.0 / 0.7457)
        assert ReferenceCurve.model_validate_json(c.model_dump_json()) == c

    def test_curve_rejections(self) -> None:
        step300 = curve()
        step300["points"] = [
            {"rpm": 2000.0 + 300 * i, "torque_crank_nm": 1.0, "power_wheel_kw": 1.0}
            for i in range(10)
        ]
        with pytest.raises(ValidationError, match="250"):
            ReferenceCurve.model_validate(step300)
        late = curve()
        late["points"] = [
            {"rpm": 3250.0 + 250 * i, "torque_crank_nm": 1.0, "power_wheel_kw": 1.0}
            for i in range(10)
        ]
        with pytest.raises(ValidationError, match="3000"):
            ReferenceCurve.model_validate(late)
        with pytest.raises(ValidationError):
            ReferenceCurve.model_validate(curve(license=""))
        with pytest.raises(ValidationError, match="egt_c"):
            ReferenceCurve.model_validate(curve(quantities=["egt_c"]))
        with pytest.raises(ValidationError):
            ReferenceCurve.model_validate(curve(benchmark_id="v2"))
        with pytest.raises(ValidationError):
            ReferenceCurvePoint(rpm=400.0)

    def test_curve_list_response(self) -> None:
        resp = ReferenceCurveListResponse(
            vehicle_id="hatch-20t-gdi",
            catalog_sha256=SHA,
            benchmark_sha256="b" * 64,
            items=[ReferenceCurve.model_validate(curve())],
        )
        dumped = copy.deepcopy(resp.model_dump(mode="json"))
        assert dumped["benchmark_id"] == "reference-benchmark-baseline-v1"
        assert ReferenceCurveListResponse.model_validate(dumped) == resp
