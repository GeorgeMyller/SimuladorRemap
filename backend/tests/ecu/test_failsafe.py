"""Failsafe: EGT do coletor, lambda pobre, ECT, óleo, sobrevelocidade e sensor.

Fontes: RF-22; D-BUS-04; T144.
"""

from __future__ import annotations

from typing import Any

import pytest

from simremap.ecu.contracts import FailsafeRule
from simremap.ecu.limits import default_failsafe_rules
from simremap.ecu.runtime import EcuRuntime

DT = 0.001


def _rt(
    content_factory: Any,
    runtime_factory: Any,
    tb: Any,
    rules: list[FailsafeRule] | None = None,
    **extra: Any,
) -> EcuRuntime:
    rules = rules if rules is not None else default_failsafe_rules(950.0, overspeed_rpm=7500.0)
    strategies = {
        "failsafe": {"kind": "failsafe", "rules": [r.model_dump() for r in rules], **extra},
        "boost_control": {"kind": "boost_control", "overboost_kpa": 400.0},
    }
    rt: EcuRuntime = runtime_factory(content_factory(tb.full_tables(4), strategies))
    return rt


def _run(rt: EcuRuntime, sensors: Any, start: float, seconds: float, **kw: Any) -> Any:
    out = None
    first = round(start / DT)
    for i in range(first, first + round(seconds / DT)):
        out = rt.step(sensors(t_sim_s=i * DT, tick=i, **kw), DT)
    return out


def test_lean_under_load_boost_cut_after_confirm(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """λ medido > alvo + 0,10 com MAP ≥ 150 kPa por 0,3 s ⇒ boost_cut."""
    rt = _rt(content_factory, runtime_factory, tb)
    lean = dict(map_kpa=190.0, tps_pct=100.0, lambda_measured=0.97)
    out = _run(rt, sensors, 0.0, 0.299, **lean)
    assert out.status.failsafe_actions == []
    assert out.commands.wastegate_duty_pct > 0.0
    out = _run(rt, sensors, 0.299, 0.002, **lean)
    assert out.status.failsafe_actions == ["boost_cut"]
    assert out.commands.wastegate_duty_pct == 0.0
    assert out.status.arbitration_winner == "failsafe"
    # Liberação: condição falsa por release_s (2 s).
    ok = dict(map_kpa=190.0, tps_pct=100.0, lambda_measured=0.85)
    out = _run(rt, sensors, 0.4, 1.9, **ok)
    assert out.status.failsafe_actions == ["boost_cut"]
    kinds: list[str] = []
    for i in range(2300, 2500):
        res = rt.step(sensors(t_sim_s=i * DT, tick=i, **ok), DT)
        kinds += [e.kind for e in res.events]
    assert kinds == ["failsafe_release"]
    assert res.status.failsafe_actions == []


def test_lean_rule_ignored_at_low_map(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, tb)
    out = _run(rt, sensors, 0.0, 0.5, map_kpa=120.0, lambda_measured=1.0)
    assert out.status.failsafe_actions == []


def test_egt_high_reduces_boost_target_30kpa(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """EGT do coletor > limite por 0,5 s reduz o alvo de boost em 30 kPa.

    ``egt_c`` por cilindro não conta (D-BUS-04).
    """
    rt = _rt(content_factory, runtime_factory, tb)
    hot_cyl = _run(rt, sensors, 0.0, 1.0, tps_pct=100.0, egt_c=[1100.0] * 4, egt_collector_c=900.0)
    assert hot_cyl.status.boost_target_kpa == 200.0  # D-BUS-04: só egt_collector_c conta
    out = _run(rt, sensors, 1.0, 0.499, tps_pct=100.0, egt_collector_c=960.0)
    assert out.status.boost_target_kpa == 200.0
    out = _run(rt, sensors, 1.499, 0.002, tps_pct=100.0, egt_collector_c=960.0)
    assert out.status.boost_target_kpa == pytest.approx(170.0)
    assert out.status.failsafe_actions == ["boost_reduce", "enrich"]
    assert out.status.lambda_target == pytest.approx(0.85 - 0.05)
    trips = [
        e
        for e in rt.step(
            sensors(t_sim_s=1.6, tick=1600, tps_pct=100.0, egt_collector_c=960.0), DT
        ).events
    ]
    assert trips == []
    # Liberação só abaixo do limiar − 20 °C por 2 s.
    out = _run(rt, sensors, 2.0, 3.0, tps_pct=100.0, egt_collector_c=940.0)
    assert out.status.failsafe_actions == ["boost_reduce", "enrich"]
    out = _run(rt, sensors, 5.0, 2.1, tps_pct=100.0, egt_collector_c=920.0)
    assert out.status.failsafe_actions == []


def test_egt_critical_cut_and_rev_limit(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, tb)
    out = _run(rt, sensors, 0.0, 0.25, rpm=5000.0, tps_pct=100.0, egt_collector_c=990.0)
    assert "boost_cut" in out.status.failsafe_actions
    assert "rev_limit_reduce" in out.status.failsafe_actions
    assert out.commands.fuel_cut == [True] * 4  # 5000 rpm > 4000 rpm
    out = rt.step(
        sensors(t_sim_s=0.3, tick=300, rpm=3950.0, tps_pct=100.0, egt_collector_c=990.0), DT
    )
    assert out.commands.fuel_cut == [True] * 4  # histerese de 100 rpm
    out = rt.step(
        sensors(t_sim_s=0.31, tick=310, rpm=3850.0, tps_pct=100.0, egt_collector_c=990.0), DT
    )
    assert out.commands.fuel_cut == [False] * 4


def test_overspeed_fuel_cut_same_tick(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, tb)
    out = rt.step(sensors(rpm=7600.0), DT)
    assert out.commands.fuel_cut == [True] * 4
    assert [e.kind for e in out.events] == ["failsafe_trip"]
    assert out.events[0].detail == "overspeed"
    out = rt.step(sensors(t_sim_s=DT, tick=1, rpm=7300.0), DT)
    assert out.commands.fuel_cut == [True] * 4  # libera só abaixo de 7200 rpm
    out = rt.step(sensors(t_sim_s=2 * DT, tick=2, rpm=7100.0), DT)
    assert out.commands.fuel_cut == [False] * 4


def test_ect_high_rev_limit_and_boost_ratio(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, tb)
    out = _run(rt, sensors, 0.0, 1.01, rpm=5000.0, tps_pct=100.0, ect_c=115.0)
    assert out.status.boost_target_kpa == pytest.approx(100.0)  # 50 % do alvo
    assert out.commands.fuel_cut == [True] * 4  # 5000 > 4500 rpm
    out = _run(rt, sensors, 1.1, 11.0, rpm=4000.0, tps_pct=100.0, ect_c=104.0)
    assert out.status.failsafe_actions == []


def test_oil_pressure_low_latches_until_stop(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, tb)
    out = _run(rt, sensors, 0.0, 0.51, rpm=3000.0, oil_pressure_kpa=50.0)
    assert out.commands.fuel_cut == [True] * 4
    out = _run(rt, sensors, 1.0, 5.0, rpm=3000.0, oil_pressure_kpa=400.0)
    assert out.commands.fuel_cut == [True] * 4  # latch_until_stop
    out = rt.step(sensors(t_sim_s=7.0, tick=7000, rpm=400.0, oil_pressure_kpa=400.0), DT)
    assert out.status.failsafe_actions == []


def test_oil_pressure_threshold_without_table(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rule = FailsafeRule(
        rule_id="oil_pressure_low", threshold=150.0, confirm_s=0.0, actions=["fuel_cut"]
    )
    rt: EcuRuntime = runtime_factory(
        content_factory(strategies={"failsafe": {"kind": "failsafe", "rules": [rule.model_dump()]}})
    )
    assert rt.step(sensors(oil_pressure_kpa=100.0), DT).commands.fuel_cut == [True] * 4


def test_sensor_fault_map_substitution(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """EC-04: MAP inválido ⇒ último valor por 50 ms, depois 100 kPa e sensor_fault.

    A regra ``sensor_fault`` aplica ``boost_cut`` e limite de 3000 rpm.
    """
    rt = _rt(content_factory, runtime_factory, tb)
    rt.step(sensors(rpm=3500.0, map_kpa=180.0, tps_pct=100.0), DT)
    kinds: list[str] = []
    loads = []
    for i in range(1, 120):
        bad = sensors(t_sim_s=i * DT, tick=i, rpm=3500.0, tps_pct=100.0).model_copy(
            update={"map_kpa": float("nan")}
        )
        out = rt.step(bad, DT)
        kinds += [e.kind for e in out.events]
        loads.append(out.status.load_pct)
    assert loads[0] == pytest.approx(180.0)  # último valor válido
    assert loads[-1] == pytest.approx(100.0)  # 100 kPa / 100 kPa de baro
    assert kinds == ["sensor_fault", "failsafe_trip"]
    assert out.status.failsafe_actions == ["boost_cut", "rev_limit_reduce"]
    assert out.commands.wastegate_duty_pct == 0.0
    assert out.commands.fuel_cut == [True] * 4  # 3500 > 3000 rpm
    out = _run(rt, sensors, 0.2, 2.1, rpm=2500.0, map_kpa=150.0)
    assert out.status.failsafe_actions == []


def test_temperature_out_of_range_clamped_then_fault(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """EC-15: IAT fora de −40..150 °C é limitado; persistindo 50 ms, sensor_fault."""
    rt = _rt(content_factory, runtime_factory, tb)
    out = rt.step(sensors(iat_c=-60.0), DT)
    assert out.events == []
    assert rt.ctx.iat_c == -40.0
    kinds = []
    for i in range(1, 60):
        kinds += [e.kind for e in rt.step(sensors(t_sim_s=i * DT, tick=i, iat_c=-60.0), DT).events]
    assert "sensor_fault" in kinds
    bad = sensors(t_sim_s=0.1, tick=100).model_copy(update={"ect_c": float("inf")})
    rt.step(bad, DT)
    assert rt.ctx.ect_c == 90.0  # não finito: último válido


def test_ignition_retard_action(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rule = FailsafeRule(
        rule_id="ect_high",
        threshold=100.0,
        confirm_s=0.0,
        actions=["ignition_retard"],
        action_value=4.0,
    )
    rt: EcuRuntime = runtime_factory(
        content_factory(strategies={"failsafe": {"kind": "failsafe", "rules": [rule.model_dump()]}})
    )
    out = rt.step(sensors(ect_c=105.0), DT)
    assert out.commands.ignition_advance_deg == [21.0] * 4
    assert out.status.failsafe_actions == ["ignition_retard"]


def test_failsafe_disabled(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, tb, enabled=False)
    assert rt.step(sensors(rpm=7900.0), DT).commands.fuel_cut == [False] * 4
