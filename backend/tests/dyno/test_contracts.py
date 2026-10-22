"""Contratos do dyno-bench (T037, T040 a T042; dyno RF-01, RF-11, RF-13, RF-18, RF-25, RF-26)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from simremap.dyno.contracts import (
    RUN_STATE_TRANSITIONS,
    TERMINAL_RUN_STATES,
    AbortReason,
    AmbientConditions,
    DynoCurvePoint,
    DynoLoad,
    DynoRigConfig,
    DynoRun,
    DynoRunRequest,
    ProbeOverrides,
    PullResult,
    RunState,
    RunStatePayload,
    RunSummary,
    RunType,
    SessionCreateRequest,
    SimulationSession,
    SteadyStateCell,
    can_transition,
)

SESSION_ID = "0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c"
RUN_ID = "01JAB0000000000000000000AB"
SHA = "c" * 64


def load(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "reflected_inertia_kg_m2": 1.2,
        "load_torque_crank_nm": 50.0,
        "gear": 4,
        "wheel_to_crank_ratio": 3.9,
        "pedal_pct": 100.0,
        "fan_air_speed_m_s": 12.0,
        "ambient": {},
    }
    data.update(over)
    return data


def curve_point(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "rpm": 3000.0,
        "t_sim_s": 5.0,
        "power_wheel_kw": 80.0,
        "power_wheel_kw_corr": 82.0,
        "power_crank_kw": 95.0,
        "power_crank_kw_corr": 97.0,
        "torque_wheel_nm": 1000.0,
        "torque_engine_nm": 300.0,
        "torque_engine_nm_corr": 306.0,
        "lambda": 0.82,
        "afr": 10.8,
        "egt_c": 880.0,
        "map_kpa": 220.0,
        "iat_c": 35.0,
        "ect_c": 90.0,
        "oil_c": 95.0,
        "ignition_deg_btdc": 12.0,
        "knock_retard_max_deg": 0.0,
    }
    data.update(over)
    return data


def summary(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "peak_whp": 220.0,
        "peak_whp_rpm": 5500.0,
        "peak_power_crank_kw": 190.0,
        "peak_torque_engine_nm": 360.0,
        "peak_torque_rpm": 3000.0,
        "lambda_min": 0.78,
        "lambda_max": 0.84,
        "egt_max_c": 910.0,
        "iat_max_c": 45.0,
        "correction_factor": 1.02,
        "correction_out_of_range": False,
        "knock_events": 0,
    }
    data.update(over)
    return data


def run(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "run_type": "sweep_pull",
        "request": {"run_type": "sweep_pull"},
        "state": "completed",
        "started_at_tick": 1000,
        "ended_at_tick": 20000,
        "calibration_id": "stock-hatch-20t-gdi-oem-stage",
        "calibration_hash": SHA,
        "seed": 42,
        "sim_hz": 1000,
        "summary": summary(),
        "curve": [curve_point()],
        "curve_sha256": SHA,
    }
    data.update(over)
    return data


class TestDynoLoad:
    def test_valid_defaults(self) -> None:
        dl = DynoLoad.model_validate(load())
        assert dl.ambient == AmbientConditions()
        assert dl.vehicle_speed_kmh == 0.0
        assert not (dl.clutch_pressed or dl.launch_switch or dl.shift_request or dl.antilag_switch)
        assert DynoLoad.model_validate_json(dl.model_dump_json()) == dl

    @pytest.mark.parametrize(
        "over",
        [
            {"load_torque_crank_nm": -1.0},
            {"pedal_pct": 101.0},
            {"gear": -1},
            {"load_torque_nm": 1.0},
            {"reflected_inertia_kgm2": 1.0},
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            DynoLoad.model_validate(load(**over))


class TestSession:
    def test_create_defaults(self) -> None:
        req = SessionCreateRequest(vehicle_id="hatch-20t-gdi")
        assert req.profile_id == "oem-stage"
        assert req.sim_hz == 1000
        assert req.seed is None
        assert req.fuel_id is None
        assert req.physics_faults == []
        assert req.attempt_id is None
        assert req.ambient.pressure_kpa == 99.0
        assert req.rig.roller_inertia_kg_m2 == 300.0

    def test_create_r1_fields(self) -> None:
        req = SessionCreateRequest.model_validate(
            {
                "vehicle_id": "hatch-20t-gdi",
                "fuel_id": "e100",
                "physics_faults": [{"kind": "fuel_pump_weak", "fuel_pump_max_lph": 60}],
                "attempt_id": "6c1f0a7e-1d2b-4c3a-9f10-2b3c4d5e6f70",
            }
        )
        assert len(req.physics_faults) == 1
        assert SessionCreateRequest.model_validate_json(req.model_dump_json()) == req

    @pytest.mark.parametrize(
        "over",
        [
            {"sim_hz": 99},
            {"sim_hz": 1001},
            {"seed": -1},
            {"seed": 2**63},
            {"fuel_id": "e85"},
            {"profile_id": "foo"},
            {"vehicle_id": "HATCH"},
            {"physics_faults": [{"kind": "boost_leak", "leak_area_mm2": 1.0}] * 9},
            {"attempt_id": "not-a-uuid"},
            {"ambient": {"temperature_c": 60.0}},
            {"ambient": {"relative_humidity": 1.5}},
            {"rig": {"accel_window_ticks": 20}},
            {"rig": {"rpm_pid": [1.0, -1.0, 0.0]}},
            {"extra": True},
        ],
    )
    def test_create_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            SessionCreateRequest.model_validate({"vehicle_id": "hatch-20t-gdi"} | over)

    def test_simulation_session(self) -> None:
        session = SimulationSession(
            vehicle_id="hatch-20t-gdi",
            session_id=SESSION_ID,
            seed=7,
            calibration_id="stock-hatch-20t-gdi-oem-stage",
            fuel_id="e27",
            state="ready",
            created_at=datetime(2026, 10, 18, tzinfo=UTC),
        )
        assert session.ecu_state == "oem"
        assert session.engine_locked is False
        assert SimulationSession.model_validate_json(session.model_dump_json()) == session
        with pytest.raises(ValidationError):
            SimulationSession.model_validate(session.model_dump() | {"state": "queued"})
        with pytest.raises(ValidationError):
            SimulationSession.model_validate(
                session.model_dump() | {"created_at": datetime(2026, 1, 1)}
            )

    def test_rig_defaults(self) -> None:
        rig = DynoRigConfig()
        assert rig.rpm_pid == (2.0, 4.0, 0.02)
        assert rig.accel_window_ticks % 2 == 1


class TestRunRequest:
    def test_defaults(self) -> None:
        req = DynoRunRequest(run_type=RunType.SWEEP_PULL)
        assert (req.gear, req.start_rpm, req.ramp_rate_rpm_s) == (4, 2000.0, 300.0)
        assert req.smoothing_window == 5
        assert req.probe is None
        assert req.effective_end_rpm(6500.0) == 6300.0
        assert req.rpm_range_ok(6500.0)

    def test_rpm_range(self) -> None:
        req = DynoRunRequest(run_type="sweep_pull", start_rpm=3000.0, end_rpm=3400.0)  # type: ignore[arg-type]
        assert not req.rpm_range_ok(6500.0)
        capped = DynoRunRequest(run_type="sweep_pull", end_rpm=9000.0)  # type: ignore[arg-type]
        assert capped.effective_end_rpm(6500.0) == 6500.0

    @pytest.mark.parametrize(
        "data",
        [
            {"run_type": "sweep_pull", "smoothing_window": 4},
            {"run_type": "sweep_pull", "smoothing_window": 13},
            {"run_type": "steady_state_hold"},
            {"run_type": "sweep_pull", "cells": [{"rpm": 3000, "pedal_pct": 50}]},
            {"run_type": "steady_state_hold", "cells": [{"rpm": 3000}]},
            {
                "run_type": "steady_state_hold",
                "cells": [{"rpm": 3000, "pedal_pct": 5, "map_kpa": 90}],
            },
            {"run_type": "multi_pull", "pull_count": 1},
            {"run_type": "sweep_pull", "ramp_rate_rpm_s": 2000},
            {"run_type": "sweep_pull", "probe": {"ignition_offset_deg": 11}},
            {"run_type": "sweep_pull", "probe": {"damage_enabled": True}},
            {"run_type": "queued"},
        ],
    )
    def test_rejections(self, data: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            DynoRunRequest.model_validate(data)

    def test_steady_state_and_probe(self) -> None:
        req = DynoRunRequest.model_validate(
            {
                "run_type": "steady_state_hold",
                "cells": [{"rpm": 3000, "map_kpa": 150}, {"rpm": 4000, "pedal_pct": 80}],
                "probe": {"ignition_offset_deg": 2.0, "knock_control_open_loop": True},
            }
        )
        assert isinstance(req.cells[0], SteadyStateCell)
        assert req.probe == ProbeOverrides(ignition_offset_deg=2.0, knock_control_open_loop=True)
        assert req.probe is not None and req.probe.damage_enabled is False
        assert DynoRunRequest.model_validate_json(req.model_dump_json()) == req


class TestStateMachine:
    def test_transitions(self) -> None:
        assert can_transition(RunState.IDLE, RunState.ARMING)
        assert can_transition(RunState.RUNNING, RunState.ENGINE_FAILED)
        assert not can_transition(RunState.IDLE, RunState.RUNNING)
        assert not can_transition(RunState.COASTDOWN, RunState.ABORTED)
        for terminal in TERMINAL_RUN_STATES:
            assert RUN_STATE_TRANSITIONS[terminal] == frozenset()
        assert set(RUN_STATE_TRANSITIONS) == set(RunState)

    def test_enum_values(self) -> None:
        assert RunState.values()[0] == "idle"
        assert len(AbortReason.values()) == 8
        assert "state IN ('idle'" in RunState.check_sql("state")


class TestRunModels:
    def test_curve_point_alias(self) -> None:
        point = DynoCurvePoint.model_validate(curve_point())
        assert point.lambda_ == 0.82
        dumped = point.model_dump()
        assert "lambda" in dumped
        assert "lambda_" not in dumped
        assert DynoCurvePoint.model_validate_json(point.model_dump_json()) == point
        by_name = curve_point()
        by_name["lambda_"] = by_name.pop("lambda")
        assert DynoCurvePoint.model_validate(by_name) == point

    def test_summary(self) -> None:
        with pytest.raises(ValidationError):
            RunSummary.model_validate(summary(lambda_min=0.9, lambda_max=0.8))
        with pytest.raises(ValidationError):
            RunSummary.model_validate(summary(knock_events=-1))

    def test_run_round_trip(self) -> None:
        dyno_run = DynoRun.model_validate(run())
        assert dyno_run.persisted is True
        assert DynoRun.model_validate_json(dyno_run.model_dump_json()) == dyno_run

    def test_multi_pull(self) -> None:
        pull = PullResult(
            pull_index=1,
            state=RunState.COMPLETED,
            summary=RunSummary.model_validate(summary()),
            curve=[DynoCurvePoint.model_validate(curve_point())],
        )
        dyno_run = DynoRun.model_validate(
            run(
                run_type="multi_pull",
                request={"run_type": "multi_pull"},
                pulls=[pull.model_dump()],
                repeatability={"peak_whp_spread_pct": 1.2, "peak_torque_spread_pct": 0.8},
            )
        )
        assert len(dyno_run.pulls) == 1

    @pytest.mark.parametrize(
        "over",
        [
            {"run_type": "baseline_pull"},
            {"state": "aborted"},
            {"state": "completed", "abort_reason": "user_abort"},
            {"ended_at_tick": 10},
            {"run_id": "01jab0000000000000000000ab"},
            {"calibration_hash": "x"},
            {"pulls": [{"pull_index": 1, "state": "completed", "summary": summary(), "curve": []}]},
        ],
    )
    def test_run_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            DynoRun.model_validate(run(**over))

    def test_engine_failed_with_reason(self) -> None:
        dyno_run = DynoRun.model_validate(
            run(state="engine_failed", abort_reason="catastrophic_failure")
        )
        assert dyno_run.abort_reason == AbortReason.CATASTROPHIC_FAILURE
        aborted = DynoRun.model_validate(run(state="aborted", abort_reason="user_abort"))
        assert aborted.abort_reason == AbortReason.USER_ABORT

    def test_run_state_payload(self) -> None:
        payload = RunStatePayload(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            run_type=RunType.MULTI_PULL,
            state=RunState.RUNNING,
            previous_state=RunState.ARMING,
            phase="pull",
            pull_index=1,
            pull_count=3,
            progress_pct=12.5,
            rpm=2010.0,
        )
        assert RunStatePayload.model_validate_json(payload.model_dump_json()) == payload
        with pytest.raises(ValidationError):
            RunStatePayload.model_validate(payload.model_dump() | {"progress_pct": 101})
