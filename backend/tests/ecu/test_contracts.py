"""Contratos de fronteira da ECU (T050; ecu RF-30, RF-33; D-BUS-01, D-BUS-09)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from simremap.ecu.contracts import (
    AXIS_UNITS,
    AntilagConfig,
    Axis,
    AxisQuantity,
    BoostControlConfig,
    ClosedLoopConfig,
    EcuEvent,
    EcuStatus,
    EcuStepResult,
    EcuValidationError,
    FailsafeConfig,
    FailsafeRule,
    KnockControlConfig,
    OverrunConfig,
    PowershiftConfig,
    RevLimiterConfig,
    StrategyConfig,
    StrategyKind,
    TableKind,
    TwoStepConfig,
    VvtConfig,
)
from simremap.physics.contracts import ActuatorCommands

_strategy: TypeAdapter[Any] = TypeAdapter(StrategyConfig)
SHA = "e" * 64


def status(n: int = 4, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "t_sim_s": 1.0,
        "lambda_target": 0.82,
        "stft_pct": 1.5,
        "ltft_pct": 0.0,
        "closed_loop_active": False,
        "fuel_mass_mg": [60.0] * n,
        "injector_pw_ms": [5.0] * n,
        "inj_duty_pct": 40.0,
        "ignition_advance_deg": [15.0] * n,
        "knock_retard_deg": [0.0] * n,
        "boost_target_kpa": 220.0,
        "wastegate_duty_pct": 35.0,
        "limiter_state": "off",
        "active_strategies": ["knock_control", "boost_control"],
        "arbitration_winner": "normal",
        "failsafe_actions": [],
        "load_pct": 150.0,
        "torque_request_nm": None,
        "calibration_hash": SHA,
    }
    data.update(over)
    return data


def commands(n: int = 4) -> ActuatorCommands:
    return ActuatorCommands(
        t_sim_s=1.0,
        injector_pw_ms=[5.0] * n,
        ignition_advance_deg=[15.0] * n,
        fuel_cut=[False] * n,
        spark_cut=[False] * n,
        throttle_pct=100.0,
    )


class TestStrategies:
    @pytest.mark.parametrize(
        ("model", "kind"),
        [
            (ClosedLoopConfig, "closed_loop"),
            (KnockControlConfig, "knock_control"),
            (BoostControlConfig, "boost_control"),
            (RevLimiterConfig, "rev_limiter"),
            (TwoStepConfig, "two_step"),
            (AntilagConfig, "antilag"),
            (PowershiftConfig, "powershift"),
            (OverrunConfig, "overrun"),
            (VvtConfig, "vvt"),
        ],
    )
    def test_defaults_and_discriminator(self, model: type[Any], kind: str) -> None:
        cfg = model()
        assert cfg.kind == kind
        assert cfg.enabled is True
        parsed = _strategy.validate_python(cfg.model_dump())
        assert type(parsed) is model
        assert _strategy.validate_json(_strategy.dump_json(parsed)) == cfg

    def test_ten_kinds(self) -> None:
        assert len(StrategyKind) == 10
        assert StrategyKind("vvt") is StrategyKind.VVT

    def test_failsafe(self) -> None:
        rule = FailsafeRule(
            rule_id="egt_high",
            threshold=950.0,
            confirm_s=0.5,
            actions=["boost_reduce", "enrich"],
            action_value=30.0,
        )
        cfg = FailsafeConfig(rules=[rule])
        parsed = _strategy.validate_python(cfg.model_dump())
        assert isinstance(parsed, FailsafeConfig)
        with pytest.raises(ValidationError, match="duplicado"):
            FailsafeConfig(rules=[rule, rule])
        with pytest.raises(ValidationError):
            FailsafeRule(rule_id="egt_high", threshold=1, confirm_s=0.5, actions=[])
        with pytest.raises(ValidationError):
            FailsafeRule(rule_id="egt_high", threshold=1, confirm_s=6.0, actions=["fuel_cut"])
        with pytest.raises(ValidationError, match="duplicados"):
            FailsafeRule(
                rule_id="overspeed", threshold=1, confirm_s=0, actions=["fuel_cut", "fuel_cut"]
            )

    @pytest.mark.parametrize(
        "data",
        [
            {"kind": "launch_control"},
            {"kind": "closed_loop", "trim_limit_pct": 30.0},
            {"kind": "closed_loop", "rpm_min": 8000.0},
            {"kind": "knock_control", "retard_step_deg": 5.0, "max_retard_deg": 4.0},
            {"kind": "rev_limiter", "hard_rpm": 13000.0},
            {"kind": "rev_limiter", "cut_mode": "throttle_cut"},
            {"kind": "two_step", "lambda_target": 0.5},
            {"kind": "antilag", "rpm_min": 7000.0, "rpm_max": 6000.0},
            {"kind": "overrun", "dfco_resume_rpm": 1600.0},
            {"kind": "overrun", "pops_rpm_min": 7000.0, "pops_rpm_max": 6000.0},
            {"kind": "powershift", "cut_time_ms": 10.0},
            {"kind": "boost_control", "unknown": 1},
        ],
    )
    def test_rejections(self, data: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            _strategy.validate_python(data)


class TestAxis:
    def test_valid(self) -> None:
        axis = Axis(quantity=AxisQuantity.RPM, values=[1000.0, 2000.0, 3000.0])
        assert axis.unit == "rev/min"
        assert set(AXIS_UNITS) == {q.value for q in AxisQuantity}
        assert len(TableKind) == 32

    @pytest.mark.parametrize(
        ("values", "code"),
        [
            ([1.0, 1.0], "TABLE_AXIS_NOT_MONOTONIC"),
            ([2.0, 1.0], "TABLE_AXIS_NOT_MONOTONIC"),
            ([1.0, float("nan")], "TABLE_VALUE_NOT_FINITE"),
            ([float(i) for i in range(33)], "TABLE_SIZE_EXCEEDED"),
        ],
    )
    def test_codes(self, values: list[float], code: str) -> None:
        with pytest.raises(ValidationError) as info:
            Axis(quantity=AxisQuantity.MAP_KPA, values=values)
        error = info.value.errors()[0]["ctx"]["error"]
        assert isinstance(error, EcuValidationError)
        assert error.code == code

    def test_too_short(self) -> None:
        with pytest.raises(ValidationError):
            Axis(quantity=AxisQuantity.RPM, values=[1.0])


class TestEcuStatus:
    def test_valid_round_trip(self) -> None:
        st = EcuStatus.model_validate(status())
        assert st.n_cyl == 4
        assert st.torque_request_nm is None
        assert EcuStatus.model_validate_json(st.model_dump_json()) == st

    def test_oem_torque_request(self) -> None:
        st = EcuStatus.model_validate(status(torque_request_nm=320.0, load_pct=95.0))
        assert st.torque_request_nm == 320.0

    @pytest.mark.parametrize(
        "over",
        [
            {"knock_retard_deg": [0.0] * 3},
            {"ign_advance_deg": [10.0] * 4},
            {"limiter_state": "medium"},
            {"arbitration_winner": "magic"},
            {"load_pct": 301.0},
            {"calibration_hash": "abc"},
            {"wastegate_duty_pct": 101.0},
            {
                "fuel_mass_mg": [1.0] * 9,
                "injector_pw_ms": [1.0] * 9,
                "ignition_advance_deg": [1.0] * 9,
                "knock_retard_deg": [0.0] * 9,
            },
        ],
    )
    def test_rejections(self, over: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            EcuStatus.model_validate(status(**over))


class TestEventsAndStep:
    def test_event(self) -> None:
        ev = EcuEvent(t_sim_s=2.0, kind="limiter_hit", value=7004.0)
        assert ev.detail == ""
        assert EcuEvent.model_validate_json(ev.model_dump_json()) == ev
        with pytest.raises(ValidationError):
            EcuEvent(t_sim_s=2.0, kind="explode")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            EcuEvent(t_sim_s=2.0, kind="knock_retard", cylinder=9)

    def test_step_result(self) -> None:
        result = EcuStepResult(commands=commands(), status=EcuStatus.model_validate(status()))
        assert result.events == []
        assert not hasattr(result, "__dict__")
        with pytest.raises(ValueError, match="n_cyl"):
            EcuStepResult(commands=commands(6), status=EcuStatus.model_validate(status()))
