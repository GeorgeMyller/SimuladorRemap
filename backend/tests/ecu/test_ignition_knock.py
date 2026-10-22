"""Avanço por cilindro e knock control sobre ``knock_intensity`` 0–1.

Fontes: RF-11, RF-13; D-BUS-05; T141.
"""

from __future__ import annotations

from typing import Any

import pytest

from simremap.ecu.runtime import EcuRuntime

DT = 0.001


def test_rf11_final_advance_per_cylinder(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    """Base 25°, trim cil. 3 = −2°, IAT +0°, ECT −1°, retardo 3° ⇒ cil. 3 = 19°, outros 21°."""
    tables = tb.base_tables()
    tables["ign_trim_3"] = tb.t3("ign_trim_3", "ignition_trim_cyl", "°", -2.0, cylinder=3)
    tables["ign_corr_iat"] = tb.t2("ign_corr_iat", "ign_corr_iat", "°", 0.0, x=[0, 100], xq="iat_c")
    tables["ign_corr_ect"] = tb.t2(
        "ign_corr_ect", "ign_corr_ect", "°", -1.0, x=[0, 120], xq="ect_c"
    )
    rt: EcuRuntime = runtime_factory(
        content_factory(tables, {"knock_control": {"kind": "knock_control"}})
    )
    rt.knock.retard[:] = [3.0, 3.0, 3.0, 3.0]
    rt.knock.last_event_t[:] = [0.0] * 4  # sem recuperação neste tick
    out = rt.step(sensors(), DT)
    assert out.commands.ignition_advance_deg == [
        pytest.approx(21.0),
        pytest.approx(21.0),
        pytest.approx(19.0),
        pytest.approx(21.0),
    ]
    assert out.status.ignition_advance_deg == out.commands.ignition_advance_deg


def test_advance_clamped(content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any) -> None:
    tables = tb.base_tables()
    tables["ignition_base"] = tb.t3("ignition_base", "ignition_base", "°BTDC", 58.0)
    tables["ign_corr_iat"] = tb.t2(
        "ign_corr_iat", "ign_corr_iat", "°", 10.0, x=[0, 100], xq="iat_c"
    )
    out = runtime_factory(content_factory(tables)).step(sensors(), DT)
    assert out.commands.ignition_advance_deg == [60.0] * 4
    tables["ignition_base"] = tb.t3("ignition_base", "ignition_base", "°BTDC", -20.0)
    tables["ign_corr_iat"] = tb.t2(
        "ign_corr_iat", "ign_corr_iat", "°", -15.0, x=[0, 100], xq="iat_c"
    )
    out = runtime_factory(content_factory(tables)).step(sensors(), DT)
    assert out.commands.ignition_advance_deg == [-20.0] * 4


def _knock_content(content_factory: Any, tb: Any, **cfg: Any) -> Any:
    tables = tb.base_tables()
    tables["knock_threshold"] = tb.t2(
        "knock_threshold", "knock_threshold", "adimensional", 0.3, x=[1000, 8000], xq="rpm"
    )
    return content_factory(tables, {"knock_control": {"kind": "knock_control", **cfg}})


def _knock(cyl: int, value: float, n: int = 4) -> list[float]:
    out = [0.0] * n
    out[cyl - 1] = value
    return out


def test_rf13_five_events_cap_at_max_and_recovery(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt: EcuRuntime = runtime_factory(_knock_content(content_factory, tb))
    rpm = 3000.0
    cycle_ticks = int(120 / rpm / DT)  # 40 ticks por ciclo
    tick = 0
    events = []
    for _ in range(5):
        out = rt.step(
            sensors(t_sim_s=tick * DT, tick=tick, rpm=rpm, knock_intensity=_knock(4, 0.6)), DT
        )
        events += [e for e in out.events if e.kind == "knock_retard"]
        tick += cycle_ticks
    assert rt.knock.retard == [0.0, 0.0, 0.0, 8.0]
    assert len(events) == 5 and all(e.cylinder == 4 for e in events)
    assert [e.value for e in events] == [2.0, 4.0, 6.0, 8.0, 8.0]
    last_event_t = (tick - cycle_ticks) * DT
    # Até 0,5 s após o último evento o retardo mantém-se.
    out = rt.step(sensors(t_sim_s=last_event_t + 0.49, tick=1, rpm=rpm), DT)
    assert out.status.knock_retard_deg[3] == 8.0
    assert "knock_control" in out.status.active_strategies
    t = last_event_t + 0.5
    for i in range(1000):
        out = rt.step(sensors(t_sim_s=t + i * DT, tick=2 + i, rpm=rpm), DT)
    assert out.status.knock_retard_deg[3] == pytest.approx(7.0, abs=0.01)  # 1 °/s
    assert out.status.ignition_advance_deg[3] == pytest.approx(25.0 - 7.0, abs=0.01)
    assert out.status.ignition_advance_deg[0] == 25.0


def test_one_event_per_engine_cycle(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt: EcuRuntime = runtime_factory(_knock_content(content_factory, tb))
    for i in range(30):  # 30 ticks < 40 ticks de um ciclo a 3000 rpm
        rt.step(sensors(t_sim_s=i * DT, tick=i, rpm=3000.0, knock_intensity=_knock(2, 0.9)), DT)
    assert rt.knock.retard[1] == 2.0


def test_threshold_and_arming_conditions(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt: EcuRuntime = runtime_factory(_knock_content(content_factory, tb))
    rt.step(sensors(knock_intensity=_knock(1, 0.29)), DT)
    assert rt.knock.retard[0] == 0.0  # abaixo do limiar 0,3
    rt.step(sensors(t_sim_s=1.0, tick=1000, rpm=1200.0, knock_intensity=_knock(1, 0.9)), DT)
    assert rt.knock.retard[0] == 0.0  # RPM < rpm_min (1500)
    rt.step(sensors(t_sim_s=2.0, tick=2000, map_kpa=60.0, knock_intensity=_knock(1, 0.9)), DT)
    assert rt.knock.retard[0] == 0.0  # MAP < map_min_kpa (80)
    rt.step(sensors(t_sim_s=3.0, tick=3000, knock_intensity=_knock(1, 0.31)), DT)
    assert rt.knock.retard[0] == 2.0


def test_default_threshold_without_table(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt: EcuRuntime = runtime_factory(
        content_factory(strategies={"knock_control": {"kind": "knock_control"}})
    )
    rt.step(sensors(knock_intensity=_knock(1, 0.21)), DT)
    assert rt.knock.retard[0] == 2.0


def test_knock_open_loop_for_probes(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt: EcuRuntime = runtime_factory(_knock_content(content_factory, tb))
    rt.step(sensors(knock_intensity=_knock(1, 0.9)), DT)
    assert rt.knock.retard[0] == 2.0
    rt.set_knock_open_loop(True)
    out = rt.step(sensors(t_sim_s=1.0, tick=1000, knock_intensity=_knock(1, 0.9)), DT)
    assert out.status.knock_retard_deg == [0.0] * 4
    assert out.status.ignition_advance_deg == [25.0] * 4


def test_knock_disabled_or_absent(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    rt: EcuRuntime = runtime_factory(_knock_content(content_factory, tb, enabled=False))
    rt.step(sensors(knock_intensity=_knock(1, 0.9)), DT)
    assert rt.knock.retard == [0.0] * 4
    rt2: EcuRuntime = runtime_factory(content_factory())
    rt2.step(sensors(knock_intensity=_knock(1, 0.9)), DT)
    assert rt2.knock.retard == [0.0] * 4


def test_max_retard_hold_reduces_boost_target(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.full_tables(4)
    content = content_factory(
        tables,
        {
            "knock_control": {
                "kind": "knock_control",
                "max_retard_deg": 4.0,
                "max_retard_hold_s": 0.5,
                "boost_reduction_kpa_at_max": 25.0,
            },
            "boost_control": {"kind": "boost_control"},
        },
    )
    rt: EcuRuntime = runtime_factory(content)
    t = 0.0
    out = None
    for i in range(80):  # eventos a cada ciclo durante 1,6 s
        t = i * 0.02
        out = rt.step(
            sensors(t_sim_s=t, tick=i, rpm=6000.0, tps_pct=100.0, knock_intensity=_knock(1, 0.9)),
            DT,
        )
    assert out is not None
    assert rt.knock.retard[0] == 4.0
    assert out.status.boost_target_kpa == pytest.approx(200.0 - 25.0)
