"""Controle de boost (malha aberta + PID, alvo por marcha) e corte por overboost.

Fontes: RF-14, RF-15; T142.
"""

from __future__ import annotations

from typing import Any

import pytest

from simremap.ecu.runtime import EcuRuntime

DT = 0.001


def _boost_tables(tb: Any, gear_values: list[float] | None = None) -> dict[str, Any]:
    tables: dict[str, Any] = tb.base_tables()
    tables["boost_target"] = tb.t3(
        "boost_target", "boost_target", "kPa", 200.0, y=[0, 50, 100], yq="tps_pct"
    )
    tables["boost_duty_base"] = tb.t3(
        "boost_duty_base", "boost_duty_base", "%", 40.0, y=[100, 200, 300], yq="boost_target_kpa"
    )
    if gear_values is not None:
        tables["boost_target_gear"] = tb.t2(
            "boost_target_gear", "boost_target_gear", "kPa", gear_values, x=[1, 2, 3, 4], xq="gear"
        )
    return tables


def _overboost(rt: EcuRuntime) -> bool:
    return rt.boost.overboost_active


def _runtime(content_factory: Any, runtime_factory: Any, tb: Any, **cfg: Any) -> EcuRuntime:
    gear = cfg.pop("gear_values", None)
    rt: EcuRuntime = runtime_factory(
        content_factory(
            _boost_tables(tb, gear), {"boost_control": {"kind": "boost_control", **cfg}}
        )
    )
    return rt


def _turbo_plant(rt: EcuRuntime, sensors: Any, seconds: float) -> list[float]:
    """Turbo de referência: MAP_ss = 140 + 120·duty/100 kPa (mola a 140 kPa), τ = 0,3 s."""
    map_kpa = 100.0
    trace = []
    for i in range(int(seconds / DT)):
        out = rt.step(
            sensors(t_sim_s=i * DT, tick=i, rpm=3500.0, tps_pct=100.0, map_kpa=map_kpa), DT
        )
        duty = out.commands.wastegate_duty_pct
        target_ss = 140.0 + 120.0 * duty / 100.0
        map_kpa += (target_ss - map_kpa) * DT / 0.3
        trace.append(map_kpa)
    return trace


def test_rf14_pid_stabilizes_at_target(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(content_factory, runtime_factory, tb)
    trace = _turbo_plant(rt, sensors, 3.0)
    after = trace[int(1.5 / DT) :]
    assert all(abs(p - 200.0) <= 5.0 for p in after)
    assert max(trace) <= 200.0 + 15.0
    assert rt.boost.pid_active


def test_rf14_open_loop_uses_base_duty(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(content_factory, runtime_factory, tb, mode="open_loop")
    out = rt.step(sensors(tps_pct=100.0, map_kpa=195.0), DT)
    assert out.commands.wastegate_duty_pct == pytest.approx(40.0)
    assert out.status.wastegate_duty_pct == pytest.approx(40.0)
    assert "boost_control" not in out.status.active_strategies


def test_pid_only_inside_activation_window(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(content_factory, runtime_factory, tb)
    out = rt.step(sensors(tps_pct=100.0, map_kpa=175.0), DT)
    assert out.commands.wastegate_duty_pct == pytest.approx(40.0)  # fora da janela de 20 kPa
    out = rt.step(sensors(t_sim_s=DT, tick=1, tps_pct=100.0, map_kpa=181.0), DT)
    assert out.commands.wastegate_duty_pct > 40.0
    assert "boost_control" in out.status.active_strategies


def test_integrator_limited(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(
        content_factory,
        runtime_factory,
        tb,
        integrator_limit_pct=5.0,
        kp_pct_per_kpa=0.0,
        kd_pct_s_per_kpa=0.0,
    )
    for i in range(3000):
        out = rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=100.0, map_kpa=185.0), DT)
    assert rt.boost.integ == pytest.approx(5.0)
    assert out.commands.wastegate_duty_pct == pytest.approx(45.0)


def test_duty_clamped_0_100(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(content_factory, runtime_factory, tb, kp_pct_per_kpa=10.0)
    assert (
        rt.step(sensors(tps_pct=100.0, map_kpa=199.0 - 18.0), DT).commands.wastegate_duty_pct
        == 100.0
    )
    rt2 = _runtime(content_factory, runtime_factory, tb, kp_pct_per_kpa=10.0, overboost_kpa=400.0)
    assert rt2.step(sensors(tps_pct=100.0, map_kpa=260.0), DT).commands.wastegate_duty_pct == 0.0


def test_rf14_gear_ceiling(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(
        content_factory, runtime_factory, tb, by_gear_enabled=True, gear_values=[150, 170, 250, 250]
    )
    out = rt.step(sensors(gear=2, tps_pct=100.0, map_kpa=120.0), DT)
    assert out.status.boost_target_kpa == pytest.approx(170.0)
    out = rt.step(sensors(t_sim_s=DT, tick=1, gear=3, tps_pct=100.0, map_kpa=120.0), DT)
    assert out.status.boost_target_kpa == pytest.approx(200.0)
    off = _runtime(content_factory, runtime_factory, tb, gear_values=[150, 170, 250, 250])
    assert off.step(sensors(gear=2, tps_pct=100.0), DT).status.boost_target_kpa == 200.0


def test_no_boost_strategy_means_spring_pressure(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt: EcuRuntime = runtime_factory(content_factory(_boost_tables(tb)))
    out = rt.step(sensors(tps_pct=100.0, map_kpa=190.0), DT)
    assert out.commands.wastegate_duty_pct == 0.0
    assert out.status.boost_target_kpa == 200.0


def test_rf15_overboost_cut_with_hysteresis(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(content_factory, runtime_factory, tb, overboost_kpa=240.0, overboost_time_s=0.1)
    events = []
    out = None
    for i in range(101):  # 245 kPa durante 0,1 s
        out = rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=100.0, map_kpa=245.0), DT)
        events += [(i, e.kind) for e in out.events]
    assert out is not None
    assert events == [(100, "overboost_cut")]
    assert out.commands.wastegate_duty_pct == 0.0
    assert out.status.arbitration_winner == "failsafe"
    assert _overboost(rt)
    out = rt.step(sensors(t_sim_s=0.2, tick=200, tps_pct=100.0, map_kpa=232.0), DT)
    assert _overboost(rt) and out.commands.wastegate_duty_pct == 0.0
    out = rt.step(sensors(t_sim_s=0.3, tick=300, tps_pct=100.0, map_kpa=229.0), DT)
    assert not _overboost(rt)
    assert out.status.arbitration_winner == "normal"


def test_overboost_short_spike_ignored(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(content_factory, runtime_factory, tb, overboost_kpa=240.0, overboost_time_s=0.1)
    for i in range(50):
        rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=100.0, map_kpa=245.0), DT)
    rt.step(sensors(t_sim_s=0.05, tick=50, tps_pct=100.0, map_kpa=200.0), DT)
    for i in range(51, 120):
        rt.step(sensors(t_sim_s=i * DT, tick=i, tps_pct=100.0, map_kpa=245.0), DT)
    assert not _overboost(rt)


def test_overboost_fuel_cut_mode(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt = _runtime(
        content_factory,
        runtime_factory,
        tb,
        overboost_kpa=240.0,
        overboost_time_s=0.0,
        overboost_cut_mode="fuel_cut",
    )
    out = rt.step(sensors(tps_pct=100.0, map_kpa=250.0), DT)
    assert out.commands.fuel_cut == [True] * 4
    assert out.commands.injector_pw_ms == [0.0] * 4
