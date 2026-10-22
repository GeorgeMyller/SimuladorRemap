"""Contratos do barramento da física (T022, T023; physics RF-01, RF-18, RF-23, RF-26)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from simremap.physics.contracts import (
    ActuatorCommands,
    CombustionEvent,
    EngineState,
    KnockSignal,
    PhysicsConfig,
    PhysicsFault,
    SensorReadings,
)


def sensors(n: int = 4, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "t_sim_s": 0.5,
        "tick": 500,
        "rpm": 3000.0,
        "crank_angle_deg": 12.0,
        "cam_intake_deg": 10.0,
        "cam_exhaust_deg": -5.0,
        "map_kpa": 180.0,
        "baro_kpa": 99.0,
        "boost_pre_throttle_kpa": 190.0,
        "iat_c": 35.0,
        "ect_c": 90.0,
        "oil_temp_c": 95.0,
        "tps_pct": 100.0,
        "lambda_measured": 0.82,
        "egt_c": [850.0] * n,
        "egt_collector_c": 900.0,
        "fuel_pressure_kpa": 20000.0,
        "battery_v": 13.8,
        "knock_sensor_v": [0.05] * n,
        "knock_intensity": [0.0] * n,
    }
    data.update(over)
    return data


def commands(n: int = 4, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "t_sim_s": 0.5,
        "injector_pw_ms": [5.0] * n,
        "ignition_advance_deg": [15.0] * n,
        "fuel_cut": [False] * n,
        "spark_cut": [False] * n,
        "throttle_pct": 100.0,
    }
    data.update(over)
    return data


def event(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "cylinder": 1,
        "t_sim_s": 0.5,
        "rpm": 3000.0,
        "theta_start_deg": -20.0,
        "pressure_kpa": [2000.0, 5000.0, 8000.0],
        "t_unburned_k": [700.0, 800.0, 900.0],
        "burned_fraction": [0.0, 0.5, 1.0],
        "p_max_kpa": 8000.0,
        "theta_pmax_deg_atdc": 14.0,
        "t_unburned_max_k": 900.0,
        "rod_force_peak_n": 30000.0,
        "imep_gross_kpa": 1800.0,
        "lambda_real": 0.82,
        "fuel_octane_ron": 95.0,
        "fuel_octane_mon": 85.0,
        "misfire": False,
        "afterfire_energy_j": 0.0,
        "pop_event": False,
    }
    data.update(over)
    return data


def engine_state(n: int = 4, **over: Any) -> dict[str, Any]:
    per = {
        name: [1.0] * n
        for name in (
            "ve_true",
            "m_air_mg",
            "m_fuel_mg",
            "ignition_advance_deg",
            "burn_duration_deg",
            "p_max_kpa",
            "theta_pmax_deg_atdc",
            "t_unburned_max_k",
            "rod_force_peak_n",
            "piston_temp_c",
            "hot_spot_temp_c",
            "egt_c",
        )
    }
    data: dict[str, Any] = {
        "t_sim_s": 1.0,
        "tick": 1000,
        "rpm": 3000.0,
        "crank_angle_deg": 100.0,
        "locked": False,
        "stalled": False,
        "map_kpa": 180.0,
        "boost_pre_throttle_kpa": 190.0,
        "exhaust_manifold_kpa": 210.0,
        "t_manifold_c": 40.0,
        "t_intercooler_out_c": 38.0,
        "lambda_cyl": [0.82, None, 0.83, 0.81][:n] + [0.8] * max(0, n - 4),
        "lambda_collector": 0.82,
        "egt_collector_c": 900.0,
        "imep_gross_kpa": 1800.0,
        "pmep_kpa": 20.0,
        "fmep_kpa": 150.0,
        "torque_indicated_nm": 330.0,
        "torque_nm": 300.0,
        "power_kw": 94.0,
        "wheel_power_kw": 80.0,
        "whp": 107.3,
        "fuel_flow_g_s": 8.0,
        "bsfc_g_kwh": 300.0,
        "thermal_efficiency": 0.33,
        "turbo_rpm": 150000.0,
        "compressor_pressure_ratio": 1.9,
        "compressor_efficiency": 0.74,
        "surge_margin": 0.1,
        "wastegate_position_pct": 20.0,
        "supercharger_rpm": None,
        "supercharger_power_kw": None,
        "ect_c": 90.0,
        "iat_c": 35.0,
        **per,
    }
    data.update(over)
    return data


class TestPhysicsConfig:
    def test_defaults_and_dt(self) -> None:
        cfg = PhysicsConfig()
        assert cfg.sim_hz == 1000
        assert cfg.dt == pytest.approx(1e-3)
        assert cfg.dt_matches(0.001)
        assert not cfg.dt_matches(0.001 + 1e-9)
        assert cfg.faults == []
        assert cfg.noise.map_sigma_kpa == 0.3

    @pytest.mark.parametrize("sim_hz", [99, 1001])
    def test_sim_hz_out_of_range(self, sim_hz: int) -> None:
        with pytest.raises(ValidationError):
            PhysicsConfig(sim_hz=sim_hz)

    def test_seed_limits(self) -> None:
        assert PhysicsConfig(seed=2**63 - 1).seed == 2**63 - 1
        with pytest.raises(ValidationError):
            PhysicsConfig(seed=2**63)
        with pytest.raises(ValidationError):
            PhysicsConfig(seed=-1)

    def test_faults_max_8(self) -> None:
        fault = PhysicsFault(kind="boost_leak", leak_area_mm2=10.0)
        assert len(PhysicsConfig(faults=[fault] * 8).faults) == 8
        with pytest.raises(ValidationError):
            PhysicsConfig(faults=[fault] * 9)

    def test_frozen_and_forbid_extra(self) -> None:
        cfg = PhysicsConfig()
        with pytest.raises(ValidationError):
            cfg.sim_hz = 500
        with pytest.raises(ValidationError):
            PhysicsConfig(unknown=1)  # type: ignore[call-arg]

    def test_crank_resolution_fixed(self) -> None:
        with pytest.raises(ValidationError):
            PhysicsConfig(crank_resolution_deg=0.5)

    def test_round_trip(self) -> None:
        cfg = PhysicsConfig(
            sim_hz=500, seed=42, faults=[PhysicsFault(kind="fuel_pump_weak", fuel_pump_max_lph=60)]
        )
        assert PhysicsConfig.model_validate_json(cfg.model_dump_json()) == cfg


class TestPhysicsFault:
    @pytest.mark.parametrize(
        "data",
        [
            {"kind": "fuel_pump_weak", "fuel_pump_max_lph": 60.0},
            {"kind": "injector_clogged", "cylinder": 3, "injector_flow_factor": 0.7},
            {"kind": "boost_leak", "leak_area_mm2": 12.0},
            {"kind": "sensor_bias", "sensor_channel": "iat_c", "sensor_bias": 15.0},
            {"kind": "wastegate_stuck", "stuck_position_pct": 0.0},
        ],
    )
    def test_valid_kinds(self, data: dict[str, Any]) -> None:
        fault = PhysicsFault.model_validate(data)
        assert PhysicsFault.model_validate_json(fault.model_dump_json()) == fault

    @pytest.mark.parametrize(
        ("data", "match"),
        [
            ({"kind": "fuel_pump_weak"}, "exige fuel_pump_max_lph"),
            ({"kind": "injector_clogged", "cylinder": 1}, "injector_flow_factor"),
            ({"kind": "wastegate_stuck", "stuck_position_pct": 50, "cylinder": 2}, "não aceita"),
            ({"kind": "sensor_bias", "sensor_channel": "egt_c", "sensor_bias": 1}, "desconhecido"),
            ({"kind": "wastegate_stuck", "stuck_position_pct": 101}, "less than or equal"),
            ({"kind": "injector_clogged", "cylinder": 9, "injector_flow_factor": 0.5}, "less"),
        ],
    )
    def test_rejections(self, data: dict[str, Any], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            PhysicsFault.model_validate(data)


class TestSensorReadings:
    def test_valid_and_safe_defaults(self) -> None:
        s = SensorReadings.model_validate(sensors())
        assert s.n_cyl == 4
        assert s.sync_ok is True
        assert s.gear == 0
        assert s.pedal_pct == 0.0
        assert s.turbo_rpm is None
        assert SensorReadings.model_validate_json(s.model_dump_json()) == s

    @pytest.mark.parametrize(
        "over",
        [
            {"lambda_measured": 0.49},
            {"lambda_measured": 2.01},
            {"knock_sensor_v": [5.1, 0.0, 0.0, 0.0]},
            {"knock_intensity": [1.01, 0.0, 0.0, 0.0]},
            {"battery_v": 5.9},
            {"crank_angle_deg": 720.0},
            {"tps_pct": 100.1},
            {"egt_c": [800.0] * 3},
            {"egt_c": [], "knock_sensor_v": [], "knock_intensity": []},
            {"egt_c": [800.0] * 9, "knock_sensor_v": [0.0] * 9, "knock_intensity": [0.0] * 9},
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            SensorReadings.model_validate(sensors(**over))

    def test_knock_extremes(self) -> None:
        s = SensorReadings.model_validate(
            sensors(knock_sensor_v=[5.0, 0.0, 0.05, 2.5], knock_intensity=[1.0, 0.0, 0.0, 0.5])
        )
        assert max(s.knock_sensor_v) == 5.0


class TestActuatorCommands:
    def test_valid_defaults(self) -> None:
        c = ActuatorCommands.model_validate(commands(8))
        assert c.n_cyl == 8
        assert c.fuel_pump_duty_pct == 100.0
        assert c.wastegate_duty_pct == 0.0
        assert c.injection_end_deg_btdc is None
        assert ActuatorCommands.model_validate_json(c.model_dump_json()) == c

    @pytest.mark.parametrize(
        "over",
        [
            {"injector_pw_ms": [50.1, 1.0, 1.0, 1.0]},
            {"ignition_advance_deg": [61.0, 1.0, 1.0, 1.0]},
            {"ignition_advance_deg": [-31.0, 1.0, 1.0, 1.0]},
            {"fuel_cut": [False] * 3},
            {"injection_end_deg_btdc": [300.0] * 3},
            {"throttle_pct": -1.0},
            {"ign_advance_deg": [10.0] * 4},
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            ActuatorCommands.model_validate(commands(**over))


class TestKnockAndEvents:
    def test_knock_signal(self) -> None:
        sig = KnockSignal.silent(6)
        assert sig.intensity == [0.0] * 6
        with pytest.raises(ValidationError):
            KnockSignal(intensity=[-0.1])
        with pytest.raises(ValidationError):
            KnockSignal(intensity=[])

    def test_combustion_event(self) -> None:
        ev = CombustionEvent.model_validate(event())
        assert CombustionEvent.model_validate_json(ev.model_dump_json()) == ev
        with pytest.raises(ValidationError, match="mesmo comprimento"):
            CombustionEvent.model_validate(event(t_unburned_k=[700.0]))
        with pytest.raises(ValidationError):
            CombustionEvent.model_validate(event(afterfire_energy_j=-1.0))
        with pytest.raises(ValidationError):
            CombustionEvent.model_validate(event(cylinder=9))


class TestEngineState:
    def test_valid_round_trip(self) -> None:
        state = EngineState.model_validate(engine_state(events=[event(cylinder=2)]))
        assert state.n_cyl == 4
        assert state.lambda_cyl[1] is None
        assert state.real_time_factor is None
        assert EngineState.model_validate_json(state.model_dump_json()) == state

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValidationError, match="comprimentos diferentes"):
            EngineState.model_validate(engine_state(p_max_kpa=[1.0] * 3))

    def test_event_cylinder_beyond_n_cyl(self) -> None:
        with pytest.raises(ValidationError, match=r"fora de 1\.\.4"):
            EngineState.model_validate(engine_state(events=[event(cylinder=5)]))
