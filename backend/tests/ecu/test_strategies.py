"""Limitador, two-step, antilag, powershift e overrun com proteção de EGT (RF-16 a RF-21; T143)."""

from __future__ import annotations

from typing import Any

import pytest

from simremap.ecu.runtime import EcuRuntime

DT = 0.001


def _rt(
    content_factory: Any, runtime_factory: Any, strategies: dict[str, Any], n_cyl: int = 4
) -> EcuRuntime:
    rt: EcuRuntime = runtime_factory(content_factory(strategies=strategies), n_cyl=n_cyl)
    return rt


# --------------------------------------------------------------------------- RF-16


def _limiter(cut_mode: str = "fuel_cut") -> dict[str, Any]:
    return {
        "rev_limiter": {
            "kind": "rev_limiter",
            "hard_rpm": 7000.0,
            "soft_window_rpm": 200.0,
            "hysteresis_rpm": 100.0,
            "soft_retard_max_deg": 10.0,
            "cut_mode": cut_mode,
        }
    }


def test_rf16_soft_retard_hard_cut_and_hysteresis(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _limiter())
    out = rt.step(sensors(rpm=6900.0), DT)
    assert out.status.limiter_state == "soft"
    assert out.commands.ignition_advance_deg == [pytest.approx(25.0 - 5.0)] * 4  # 50 % de 10°
    assert out.commands.fuel_cut == [False] * 4
    out = rt.step(sensors(t_sim_s=DT, tick=1, rpm=7000.0), DT)
    assert out.commands.fuel_cut == [True] * 4
    assert out.commands.injector_pw_ms == [0.0] * 4
    assert out.status.limiter_state == "hard"
    assert out.status.arbitration_winner == "rev_limiter"
    assert [e.kind for e in out.events] == ["limiter_hit"]
    out = rt.step(sensors(t_sim_s=2 * DT, tick=2, rpm=6950.0), DT)
    assert out.commands.fuel_cut == [True] * 4 and not out.events  # histerese
    out = rt.step(sensors(t_sim_s=3 * DT, tick=3, rpm=6899.0), DT)
    assert out.commands.fuel_cut == [False] * 4
    assert out.status.limiter_state == "soft"
    out = rt.step(sensors(t_sim_s=4 * DT, tick=4, rpm=6000.0), DT)
    assert out.status.limiter_state == "off" and out.status.arbitration_winner == "normal"


def test_rf16_spark_cut_mode(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = _rt(content_factory, runtime_factory, _limiter("spark_cut"))
    out = rt.step(sensors(rpm=7100.0), DT)
    assert out.commands.spark_cut == [True] * 4
    assert out.commands.fuel_cut == [False] * 4


def test_rf16_rolling_cut_fraction_rotates(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _limiter("rolling_cut"), n_cyl=8)
    masks = []
    for i in range(200):
        out = rt.step(sensors(n_cyl=8, t_sim_s=i * DT, tick=i, rpm=6900.0), DT)
        masks.append(tuple(out.commands.spark_cut))
    assert all(sum(m) == 4 for m in masks)  # f = 0,5 ⇒ 4 de 8 cilindros
    assert len(set(masks)) > 1  # padrão rotativo pelo contador de ciclos


def test_rev_limiter_disabled(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    strategies = _limiter()
    strategies["rev_limiter"]["enabled"] = False
    out = _rt(content_factory, runtime_factory, strategies).step(sensors(rpm=7500.0), DT)
    assert out.status.limiter_state == "off" and out.commands.fuel_cut == [False] * 4


# --------------------------------------------------------------------------- RF-17


def _two_step(**cfg: Any) -> dict[str, Any]:
    return {"two_step": {"kind": "two_step", "target_rpm": 4000.0, "cut_mode": "spark_cut", **cfg}}


def test_rf17_launch_holds_target(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = _rt(content_factory, runtime_factory, _two_step())
    rpm = 3000.0
    trace = []
    for i in range(3000):
        out = rt.step(
            sensors(t_sim_s=i * DT, tick=i, rpm=rpm, tps_pct=100.0, clutch_pressed=True), DT
        )
        fired = 1.0 - sum(out.commands.spark_cut) / 4
        rpm += (2000.0 * fired - 500.0) * DT
        if i > 1500:
            trace.append(rpm)
            assert out.commands.ignition_advance_deg == [-5.0] * 4
            assert out.status.lambda_target == pytest.approx(0.85)
            assert out.status.arbitration_winner == "two_step"
    assert all(3900.0 <= r <= 4100.0 for r in trace)


def test_rf17_requires_activation_conditions(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _two_step())
    assert rt.step(sensors(tps_pct=100.0), DT).status.arbitration_winner == "normal"
    assert (
        rt.step(sensors(tps_pct=50.0, clutch_pressed=True), DT).status.arbitration_winner
        == "normal"
    )
    moving = sensors(tps_pct=100.0, clutch_pressed=True, vehicle_speed_kmh=20.0)
    assert rt.step(moving, DT).status.arbitration_winner == "normal"
    switch = _rt(content_factory, runtime_factory, _two_step(activation="launch_switch"))
    out = switch.step(sensors(tps_pct=100.0, launch_switch=True), DT)
    assert out.status.arbitration_winner == "two_step"


def test_rf17_timeout_event_and_rearm(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _two_step(max_active_s=1.0, release_ramp_s=0.0))
    kinds = []
    for i in range(1200):
        out = rt.step(
            sensors(t_sim_s=i * DT, tick=i, rpm=3000.0, tps_pct=100.0, clutch_pressed=True), DT
        )
        kinds += [e.kind for e in out.events]
    assert kinds == ["two_step_timeout"]
    assert out.status.arbitration_winner == "normal"
    rt.step(sensors(t_sim_s=1.3, tick=1300, rpm=3000.0, tps_pct=100.0), DT)  # solta a embraiagem
    out = rt.step(
        sensors(t_sim_s=1.4, tick=1400, rpm=3000.0, tps_pct=100.0, clutch_pressed=True), DT
    )
    assert out.status.arbitration_winner == "two_step"


def test_two_step_release_ramp(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = _rt(content_factory, runtime_factory, _two_step(release_ramp_s=0.2))
    rt.step(sensors(rpm=3000.0, tps_pct=100.0, clutch_pressed=True), DT)
    out = rt.step(sensors(t_sim_s=0.1, tick=100, rpm=3000.0, tps_pct=100.0), DT)
    # saída em t = 0,1 s: o retardo de 30° (25 − (−5)) desaparece em 0,2 s
    assert out.commands.ignition_advance_deg[0] == pytest.approx(-5.0)
    out = rt.step(sensors(t_sim_s=0.2, tick=200, rpm=3000.0, tps_pct=100.0), DT)
    assert out.commands.ignition_advance_deg[0] == pytest.approx(25.0 - 15.0)
    out = rt.step(sensors(t_sim_s=0.31, tick=310, rpm=3000.0, tps_pct=100.0), DT)
    assert out.commands.ignition_advance_deg[0] == pytest.approx(25.0)


def test_two_step_rolling_and_fuel_cut(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rolling = _rt(content_factory, runtime_factory, _two_step(cut_mode="rolling_cut"))
    out = rolling.step(sensors(rpm=4000.0, tps_pct=100.0, clutch_pressed=True), DT)
    assert sum(out.commands.spark_cut) == 2  # excesso a meio da banda ⇒ metade
    fuel = _rt(content_factory, runtime_factory, _two_step(cut_mode="fuel_cut"))
    out = fuel.step(sensors(rpm=4050.0, tps_pct=100.0, clutch_pressed=True), DT)
    assert out.commands.fuel_cut == [True] * 4


# --------------------------------------------------------------------------- RF-18


def _antilag(**cfg: Any) -> dict[str, Any]:
    return {"antilag": {"kind": "antilag", "air_valve_pct": 15.0, "cooldown_s": 5.0, **cfg}}


def test_rf18_antilag_active_commands(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _antilag(), n_cyl=8)
    out = rt.step(sensors(n_cyl=8, rpm=4000.0, tps_pct=5.0, antilag_switch=True), DT)
    assert out.commands.antilag_air_pct == 15.0
    assert out.commands.ignition_advance_deg == [-15.0] * 8
    assert out.status.lambda_target == pytest.approx(0.80)
    assert sum(out.commands.spark_cut) == 2  # cut_fraction 0,25 de 8
    assert out.status.arbitration_winner == "antilag"
    off = rt.step(
        sensors(n_cyl=8, t_sim_s=DT, tick=1, rpm=4000.0, tps_pct=50.0, antilag_switch=True), DT
    )
    assert off.commands.antilag_air_pct == 0.0


def test_rf18_egt_protection_and_cooldown(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    """C-04: EGT ≥ egt_max_c desliga o antilag no mesmo tick e emite antilag_protect."""
    rt = _rt(content_factory, runtime_factory, _antilag(egt_max_c=1000.0))
    on = dict(rpm=4000.0, tps_pct=5.0, antilag_switch=True)
    assert rt.step(sensors(**on), DT).commands.antilag_air_pct == 15.0
    out = rt.step(sensors(t_sim_s=0.1, tick=100, egt_collector_c=1000.0, **on), DT)
    assert out.commands.antilag_air_pct == 0.0
    assert [e.kind for e in out.events] == ["antilag_protect"]
    out = rt.step(sensors(t_sim_s=2.0, tick=2000, **on), DT)
    assert out.commands.antilag_air_pct == 0.0  # em cooldown
    out = rt.step(sensors(t_sim_s=5.2, tick=5200, **on), DT)
    assert out.commands.antilag_air_pct == 15.0


def test_rf18_max_active_time(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = _rt(content_factory, runtime_factory, _antilag(max_active_s=1.0, cooldown_s=0.5))
    kinds = []
    for i in range(1100):
        out = rt.step(
            sensors(t_sim_s=i * DT, tick=i, rpm=4000.0, tps_pct=5.0, antilag_switch=True), DT
        )
        kinds += [e.kind for e in out.events]
    assert kinds == ["antilag_protect"]
    assert out.commands.antilag_air_pct == 0.0
    out = rt.step(sensors(t_sim_s=1.6, tick=1600, rpm=4000.0, tps_pct=5.0, antilag_switch=True), DT)
    assert out.commands.antilag_air_pct == 15.0


def test_antilag_rolling_activation(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _antilag(activation="rolling"))
    assert rt.step(sensors(rpm=4000.0, tps_pct=5.0), DT).commands.antilag_air_pct == 15.0
    assert (
        rt.step(sensors(t_sim_s=DT, tick=1, rpm=2500.0, tps_pct=5.0), DT).commands.antilag_air_pct
        == 0.0
    )


# --------------------------------------------------------------------------- RF-19


def test_rf19_powershift_cuts_exactly_120_ticks(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        {"powershift": {"kind": "powershift", "cut_time_ms": 120.0}},
    )
    cut_ticks = 0
    for i in range(400):
        shift = 10 <= i < 300  # sinal mantido
        out = rt.step(
            sensors(t_sim_s=i * DT, tick=i, rpm=5000.0, tps_pct=100.0, shift_request=shift), DT
        )
        if all(out.commands.spark_cut):
            cut_ticks += 1
    assert cut_ticks == 120  # nova borda só depois da liberação do sinal
    for i in range(400, 420):
        rt.step(sensors(t_sim_s=i * DT, tick=i, rpm=5000.0, tps_pct=100.0, shift_request=True), DT)
    assert rt.powershift.cutting


def test_powershift_conditions_and_resume_ramp(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    cfg = {
        "powershift": {
            "kind": "powershift",
            "cut_time_ms": 20.0,
            "resume_retard_deg": 6.0,
            "resume_ramp_s": 0.1,
        }
    }
    rt = _rt(content_factory, runtime_factory, cfg)
    out = rt.step(sensors(rpm=2000.0, tps_pct=100.0, shift_request=True), DT)
    assert out.commands.spark_cut == [False] * 4  # rpm < min_rpm
    rt.step(sensors(t_sim_s=DT, tick=1, rpm=5000.0, tps_pct=100.0), DT)
    for i in range(2, 22):
        rt.step(sensors(t_sim_s=i * DT, tick=i, rpm=5000.0, tps_pct=100.0, shift_request=True), DT)
    out = rt.step(sensors(t_sim_s=22 * DT, tick=22, rpm=5000.0, tps_pct=100.0), DT)
    assert out.commands.spark_cut == [False] * 4
    assert out.commands.ignition_advance_deg[0] == pytest.approx(25.0 - 6.0, abs=0.1)
    out = rt.step(sensors(t_sim_s=0.072, tick=72, rpm=5000.0, tps_pct=100.0), DT)
    assert out.commands.ignition_advance_deg[0] == pytest.approx(25.0 - 3.0, abs=0.1)
    clutch = _rt(
        content_factory,
        runtime_factory,
        {"powershift": {"kind": "powershift", "trigger": "clutch", "cut_mode": "fuel_cut"}},
    )
    out = clutch.step(sensors(rpm=5000.0, tps_pct=100.0, clutch_pressed=True), DT)
    assert out.commands.fuel_cut == [True] * 4


# --------------------------------------------------------------------------- RF-20 / RF-21


def _overrun(**cfg: Any) -> dict[str, Any]:
    return {
        "overrun": {
            "kind": "overrun",
            "pops_enabled": True,
            "fuel_cut_delay_s": 1.0,
            "max_duration_s": 2.0,
            "intensity_pct": 100.0,
            "catalyst_present": False,
            **cfg,
        }
    }


def test_rf20_pops_then_delayed_cut(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _overrun())
    rt.step(sensors(rpm=4000.0, tps_pct=60.0), DT)
    out = rt.step(sensors(t_sim_s=0.01, tick=10, rpm=4000.0, tps_pct=0.0), DT)
    assert out.commands.ignition_advance_deg == [-15.0] * 4
    assert out.status.lambda_target == pytest.approx(0.90)
    assert out.commands.fuel_cut == [False] * 4
    assert out.status.arbitration_winner == "overrun"
    out = rt.step(sensors(t_sim_s=0.9, tick=900, rpm=4000.0, tps_pct=0.0), DT)
    assert out.commands.fuel_cut == [False] * 4
    out = rt.step(sensors(t_sim_s=1.02, tick=1020, rpm=4000.0, tps_pct=0.0), DT)
    assert out.commands.fuel_cut == [True] * 4  # corte de injeção após o atraso
    out = rt.step(sensors(t_sim_s=1.5, tick=1500, rpm=1100.0, tps_pct=0.0), DT)
    assert out.commands.fuel_cut == [False] * 4  # rpm < dfco_resume_rpm


def test_rf20_outside_window_dfco(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = _rt(content_factory, runtime_factory, _overrun())
    rt.step(sensors(rpm=7000.0, tps_pct=60.0), DT)
    out = rt.step(sensors(t_sim_s=0.01, tick=10, rpm=7000.0, tps_pct=0.0), DT)
    assert out.commands.fuel_cut == [False] * 4  # DFCO espera dfco_delay_s
    assert out.commands.ignition_advance_deg == [25.0] * 4
    out = rt.step(sensors(t_sim_s=0.52, tick=520, rpm=7000.0, tps_pct=0.0), DT)
    assert out.commands.fuel_cut == [True] * 4
    out = rt.step(sensors(t_sim_s=0.6, tick=600, rpm=7000.0, tps_pct=30.0), DT)
    assert out.commands.fuel_cut == [False] * 4


def test_dfco_only(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = _rt(content_factory, runtime_factory, {"overrun": {"kind": "overrun"}})
    rt.step(sensors(rpm=3000.0, tps_pct=1.0), DT)
    out = rt.step(sensors(t_sim_s=0.6, tick=600, rpm=3000.0, tps_pct=1.0), DT)
    assert out.commands.fuel_cut == [True] * 4
    disabled = _rt(
        content_factory, runtime_factory, {"overrun": {"kind": "overrun", "dfco_enabled": False}}
    )
    disabled.step(sensors(rpm=3000.0, tps_pct=1.0), DT)
    out = disabled.step(sensors(t_sim_s=0.6, tick=600, rpm=3000.0, tps_pct=1.0), DT)
    assert out.commands.fuel_cut == [False] * 4


def test_rf21_turbine_protection_same_tick(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = _rt(content_factory, runtime_factory, _overrun(egt_turbine_max_c=950.0))
    rt.step(sensors(rpm=4000.0, tps_pct=0.0), DT)
    out = rt.step(
        sensors(t_sim_s=0.1, tick=100, rpm=4000.0, tps_pct=0.0, egt_collector_c=960.0), DT
    )
    assert [e.kind for e in out.events] == ["overrun_protect"]
    assert out.commands.ignition_advance_deg == [25.0] * 4
    assert out.status.lambda_target == pytest.approx(0.85)
    out = rt.step(
        sensors(t_sim_s=0.2, tick=200, rpm=4000.0, tps_pct=0.0, egt_collector_c=900.0), DT
    )
    assert out.commands.ignition_advance_deg == [25.0] * 4  # continua suspenso neste evento


def test_rf21_catalyst_limits(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = _rt(
        content_factory,
        runtime_factory,
        _overrun(
            catalyst_present=True,
            intensity_pct=80.0,
            catalyst_max_intensity_pct=50.0,
            catalyst_max_duration_s=0.5,
        ),
    )
    assert rt.overrun.effective_intensity_pct == 50.0
    assert rt.overrun.effective_duration_s == 0.5
    rt.step(sensors(rpm=4000.0, tps_pct=0.0), DT)
    out = rt.step(sensors(t_sim_s=0.1, tick=100, rpm=4000.0, tps_pct=0.0), DT)
    assert sum(out.commands.fuel_cut) == 2  # 50 % dos cilindros com pops
    assert out.commands.ignition_advance_deg == [-15.0] * 4
    out = rt.step(sensors(t_sim_s=0.6, tick=600, rpm=4000.0, tps_pct=0.0), DT)
    assert out.commands.fuel_cut == [True] * 4  # janela limitada a 0,5 s
