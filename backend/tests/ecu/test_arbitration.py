"""Arbitragem failsafe > limitador > two-step/antilag/powershift > overrun > normal.

Fontes: RF-23, RF-24, Apêndice C; T145.
"""

from __future__ import annotations

from math import isnan
from typing import Any

import pytest

from simremap.ecu.arbitration import ArbitrationResult, EcuRequests, arbitrate
from simremap.ecu.contracts import FailsafeRule
from simremap.ecu.runtime import EcuRuntime

DT = 0.001


def _rules(*rules: FailsafeRule) -> dict[str, Any]:
    return {"kind": "failsafe", "rules": [r.model_dump() for r in rules], "overspeed_rpm": 4500.0}


OVERSPEED = FailsafeRule(rule_id="overspeed", threshold=0.0, confirm_s=0.0, actions=["fuel_cut"])
ENRICH = FailsafeRule(
    rule_id="egt_high", threshold=900.0, confirm_s=0.0, actions=["enrich"], action_value=-0.05
)
BOOST_REDUCE = FailsafeRule(
    rule_id="egt_high", threshold=900.0, confirm_s=0.0, actions=["boost_reduce"], action_value=30.0
)


def _rt(
    content_factory: Any,
    runtime_factory: Any,
    tb: Any,
    strategies: dict[str, Any],
    lam: float = 0.85,
) -> EcuRuntime:
    tables = tb.full_tables(4)
    tables["lambda_target"] = tb.t3("lambda_target", "lambda_target", "λ", lam)
    rt: EcuRuntime = runtime_factory(content_factory(tables, strategies))
    return rt


def test_c01_failsafe_fuel_cut_inhibits_two_step(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "failsafe": _rules(OVERSPEED),
            "two_step": {"kind": "two_step", "target_rpm": 4000.0},
        },
    )
    out = rt.step(sensors(rpm=4600.0, tps_pct=100.0, clutch_pressed=True), DT)
    assert out.status.arbitration_winner == "failsafe"
    assert out.commands.fuel_cut == [True] * 4
    assert rt.requests.two_step.active and rt.requests.two_step.inhibited
    assert out.commands.ignition_advance_deg == [25.0] * 4  # override do two-step inibido
    assert "two_step" not in out.status.active_strategies


def test_c02_hard_limiter_inhibits_pops(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6000.0},
            "overrun": {"kind": "overrun", "pops_enabled": True, "pops_rpm_max": 7000.0},
        },
    )
    out = rt.step(sensors(rpm=6100.0, tps_pct=0.0), DT)
    assert out.status.arbitration_winner == "rev_limiter"
    assert out.commands.fuel_cut == [True] * 4
    assert rt.requests.overrun.inhibited
    assert out.commands.ignition_advance_deg == [25.0] * 4


def test_c03_two_step_with_knock_retard(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "two_step": {"kind": "two_step", "target_rpm": 4000.0},
            "knock_control": {"kind": "knock_control"},
        },
    )
    rt.knock.retard[0] = 3.0
    rt.knock.last_event_t[0] = 0.0
    out = rt.step(sensors(rpm=3000.0, tps_pct=100.0, clutch_pressed=True), DT)
    assert out.status.arbitration_winner == "two_step"
    assert out.commands.ignition_advance_deg[0] == min(-5.0, 25.0 - 3.0)
    assert out.commands.ignition_advance_deg[1:] == [-5.0] * 3
    # Override acima do avanço normal: vale o normal com knock (escolha conservadora).
    high = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "two_step": {"kind": "two_step", "target_rpm": 4000.0, "ign_advance_deg": 30.0},
            "knock_control": {"kind": "knock_control"},
        },
    )
    high.knock.retard[0] = 3.0
    high.knock.last_event_t[0] = 0.0
    out = high.step(sensors(rpm=3000.0, tps_pct=100.0, clutch_pressed=True), DT)
    assert out.commands.ignition_advance_deg[0] == pytest.approx(22.0)


def test_c04_antilag_off_same_tick_on_egt(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(
        content_factory, runtime_factory, tb, {"antilag": {"kind": "antilag", "egt_max_c": 1000.0}}
    )
    on = dict(rpm=4000.0, tps_pct=5.0, antilag_switch=True)
    assert rt.step(sensors(**on), DT).status.arbitration_winner == "antilag"
    out = rt.step(sensors(t_sim_s=DT, tick=1, egt_collector_c=1001.0, **on), DT)
    assert out.status.arbitration_winner == "normal"
    assert [e.kind for e in out.events] == ["antilag_protect"]


@pytest.mark.parametrize(("lam_base", "expected"), [(0.85, 0.80), (0.95, 0.85)])
def test_c05_failsafe_enrich_with_two_step(  # noqa: PLR0917 - fixtures + parâmetros
    content_factory: Any,
    runtime_factory: Any,
    sensors: Any,
    tb: Any,
    lam_base: float,
    expected: float,
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "failsafe": _rules(ENRICH),
            "two_step": {"kind": "two_step", "target_rpm": 4000.0, "lambda_target": 0.85},
        },
        lam=lam_base,
    )
    out = rt.step(
        sensors(rpm=3000.0, tps_pct=100.0, clutch_pressed=True, egt_collector_c=950.0), DT
    )
    assert out.status.lambda_target == pytest.approx(min(0.85, lam_base - 0.05))
    assert out.status.lambda_target == pytest.approx(expected)
    assert out.status.arbitration_winner == "failsafe"


def test_c06_overboost_with_pid(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "boost_control": {
                "kind": "boost_control",
                "overboost_kpa": 240.0,
                "overboost_time_s": 0.0,
            }
        },
    )
    out = rt.step(sensors(rpm=4000.0, tps_pct=100.0, map_kpa=250.0), DT)
    assert out.commands.wastegate_duty_pct == 0.0
    assert out.status.arbitration_winner == "failsafe"


def test_c07_powershift_with_soft_limiter(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "rev_limiter": {
                "kind": "rev_limiter",
                "hard_rpm": 7000.0,
                "soft_window_rpm": 200.0,
                "soft_retard_max_deg": 10.0,
                "cut_mode": "rolling_cut",
            },
            "powershift": {
                "kind": "powershift",
                "cut_time_ms": 20.0,
                "resume_retard_deg": 8.0,
                "resume_ramp_s": 0.1,
            },
        },
    )
    soft = dict(rpm=6900.0, tps_pct=100.0)
    out = rt.step(sensors(shift_request=True, **soft), DT)
    assert out.commands.spark_cut == [True] * 4  # OU dos cortes
    assert out.status.arbitration_winner == "rev_limiter"
    assert set(out.status.active_strategies) >= {"rev_limiter", "powershift"}
    for i in range(1, 20):
        rt.step(sensors(t_sim_s=i * DT, tick=i, **soft), DT)
    out = rt.step(sensors(t_sim_s=20 * DT, tick=20, **soft), DT)
    assert sum(out.commands.spark_cut) == 2  # só o corte parcial do limitador
    assert out.commands.ignition_advance_deg[0] == pytest.approx(
        25.0 - 8.0, abs=0.2
    )  # menor avanço
    out = rt.step(sensors(t_sim_s=0.09, tick=90, **soft), DT)
    assert out.commands.ignition_advance_deg[0] == pytest.approx(25.0 - 5.0)  # soft (5°) > rampa


def test_c08_dfco_with_failsafe_boost_reduce(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        tb,
        {
            "failsafe": _rules(BOOST_REDUCE),
            "overrun": {"kind": "overrun", "dfco_delay_s": 0.0},
            "boost_control": {"kind": "boost_control"},
        },
    )
    out = rt.step(sensors(rpm=3000.0, tps_pct=0.0, egt_collector_c=950.0), DT)
    assert out.commands.fuel_cut == [True] * 4
    assert out.status.boost_target_kpa == pytest.approx(170.0)
    assert out.status.arbitration_winner == "failsafe"
    assert "overrun" in out.status.active_strategies


# --------------------------------------------------------------------------- arbitrate()


def test_override_tie_same_level_takes_lower_advance() -> None:
    reqs = EcuRequests(4)
    out = ArbitrationResult(4)
    reqs.two_step.active = True
    reqs.two_step.ign_override = -5.0
    reqs.antilag.active = True
    reqs.antilag.ign_override = -15.0
    reqs.overrun.active = True
    reqs.overrun.ign_override = -20.0
    arbitrate(reqs, 0.9, out)
    assert out.ign_override == -15.0  # nível 3 vence o nível 4; empate no 3: o menor
    assert out.winner == "two_step"
    assert out.active == ["two_step", "antilag", "overrun"]


def test_combination_rules_and_reset() -> None:
    reqs = EcuRequests(2)
    out = ArbitrationResult(2)
    reqs.failsafe.active = True
    reqs.failsafe.boost_ceiling_kpa = 180.0
    reqs.failsafe.lambda_delta = -0.05
    reqs.rev_limiter.active = True
    reqs.rev_limiter.ign_retard = 3.0
    reqs.overrun.active = True
    reqs.overrun.lambda_target = 0.9
    reqs.overrun.boost_ceiling_kpa = 150.0
    reqs.overrun.cut_pattern("fuel_cut", 1, 0)
    reqs.antilag.active = True
    reqs.antilag.antilag_air_pct = 12.0
    reqs.antilag.ign_retard = 5.0
    arbitrate(reqs, 0.88, out)
    assert out.boost_ceiling_kpa == 150.0
    assert out.lambda_target == pytest.approx(0.83)
    assert out.ign_retard == 5.0
    assert out.fuel_cut == [True, False]
    assert out.antilag_air_pct == 12.0
    assert isnan(out.ign_override)
    reqs.reset()
    arbitrate(reqs, 0.88, out)
    assert out.winner == "normal" and out.active == []
    assert isnan(out.lambda_target) and out.fuel_cut == [False, False]


def test_cut_pattern_rotates_and_full() -> None:
    reqs = EcuRequests(4)
    req = reqs.antilag
    req.cut_pattern("spark_cut", 1, 0)
    first = list(req.spark_cut)
    req.reset()
    req.cut_pattern("spark_cut", 1, 1)
    assert first != req.spark_cut and sum(req.spark_cut) == 1
    req.reset()
    req.cut_pattern("spark_cut", 0, 0)
    assert not req.active
    req.cut_pattern("fuel_cut", 4, 3)
    assert req.total_cut
