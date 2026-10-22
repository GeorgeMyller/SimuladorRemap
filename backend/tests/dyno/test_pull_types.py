"""Os 4 tipos de puxada no laço completo física + ECU + dano.

T123; dyno RF-06 a RF-09, RF-19; G-01, G-04, G-05.

``DynoSimTask`` em passos síncronos (sem worker) com o ``hatch-20t-gdi`` calibrado da
fixture da física e a calibração de série afinada (``dyno_helpers``).
"""

from __future__ import annotations

from typing import Any

import pytest
from dyno_helpers import make_task, run_to_result

from simremap.dyno.contracts import RunState
from simremap.dyno.runner import DynoSimTask

TORQUE_REF = 350.0
WHP_REF = 220.0


def test_g01_baseline_pull_reaches_reference_with_inertial_measurement() -> None:
    """Puxada base de série: 220 whp ± 5 % e 350 N·m ± 5 % (SAE em condições padrão)."""
    task = make_task()
    absorber_in_pull: list[float] = []
    previous = [""]

    def watch(t: DynoSimTask) -> None:
        phase = t.run.phase if t.run is not None else ""
        if phase == "pull" and previous[0] == "pull":  # ticks planeados em running
            absorber_in_pull.append(t.session.rig.last_absorber_nm)
        previous[0] = phase

    out = run_to_result(task, {"run_type": "baseline_pull", "end_rpm": 6300}, on_tick=watch)
    run = out.run
    assert run.state == RunState.COMPLETED
    assert run.summary is not None
    assert 209.0 <= run.summary.peak_whp <= 231.0
    assert 332.5 <= run.summary.peak_torque_engine_nm <= 367.5
    assert run.summary.correction_factor == pytest.approx(1.0, abs=0.001)
    # RF-06: puxada inercial pura; T_abs = 0 em 100 % dos ticks de running.
    assert absorber_in_pull and max(absorber_in_pull) == 0.0
    assert out.result["is_baseline"] is True
    assert out.states == ["arming", "running", "coastdown", "completed"]
    assert 150 <= len(run.curve) <= 400
    p = run.curve[len(run.curve) // 2]
    assert p.power_crank_kw == pytest.approx(p.power_wheel_kw / 0.85)


def test_g04_sweep_pull_tracks_300_rpm_s_ramp() -> None:
    task = make_task()
    errors: list[float] = []

    def watch(t: DynoSimTask) -> None:
        run = t.run
        if run is None or run.phase != "pull":
            return
        ref = run.request.start_rpm + run.request.ramp_rate_rpm_s * (t.t_sim_s - run.t_running)
        rpm = t.last_state.rpm if t.last_state is not None else 0.0
        if 2500.0 <= ref <= 6000.0:
            errors.append(abs(rpm - ref))

    out = run_to_result(
        task, {"run_type": "sweep_pull", "end_rpm": 6300, "ramp_rate_rpm_s": 300}, on_tick=watch
    )
    assert out.run.state == RunState.COMPLETED
    errors.sort()
    assert errors and errors[int(0.95 * len(errors))] <= 50.0
    summary = out.run.summary
    assert summary is not None
    assert 0.95 * WHP_REF <= summary.peak_whp <= 1.05 * WHP_REF
    assert 0.95 * TORQUE_REF <= summary.peak_torque_engine_nm <= 1.05 * TORQUE_REF
    assert out.result["is_baseline"] is False


def test_steady_state_hold_cells_stable_and_unreachable() -> None:
    task = make_task()
    request: dict[str, Any] = {
        "run_type": "steady_state_hold",
        "cell_timeout_s": 4.0,
        "cells": [
            {"rpm": 4000, "map_kpa": 90, "hold_s": 2.0},
            {"rpm": 4000, "pedal_pct": 100, "hold_s": 2.0},
            {"rpm": 4000, "map_kpa": 390, "hold_s": 1.0},
        ],
    }
    out = run_to_result(task, request)
    run = out.run
    assert run.state == RunState.COMPLETED
    assert [p.cell_index for p in run.curve] == [0, 1, 2]
    assert [p.stable for p in run.curve] == [True, True, False]
    assert run.curve[0].map_kpa == pytest.approx(90.0, abs=3.0)
    assert run.curve[1].rpm == pytest.approx(4000.0, abs=25.0)
    assert run.curve[2].map_kpa > 100.0  # média do último 1,0 s mesmo sem estabilizar
    assert run.curve[1].power_wheel_kw > run.curve[0].power_wheel_kw
    assert run.summary is not None and "cell_not_stable" in run.summary.event_codes
    phases = [e["payload"]["phase"] for e in out.of_type("run.state")]
    assert phases.count("cells") >= 3


def test_multi_pull_three_pulls_with_cooldown_g05() -> None:
    """N = 3 com 60 s de arrefecimento e ventilador: dispersão do pico de whp ≤ 3 %."""
    task = make_task()
    request = {
        "run_type": "multi_pull",
        "pull_count": 3,
        "cooldown_s": 60,
        "fan_on": True,
        "end_rpm": 6300,
    }
    out = run_to_result(task, request, max_s=400.0)
    run = out.run
    assert run.state == RunState.COMPLETED
    assert [p.pull_index for p in run.pulls] == [1, 2, 3]
    assert all(p.state == RunState.COMPLETED and p.curve for p in run.pulls)
    assert run.repeatability is not None
    assert run.repeatability["peak_whp_spread_pct"] <= 3.0
    assert "peak_torque_spread_pct" in run.repeatability
    payloads = [e["payload"] for e in out.of_type("run.state")]
    cooldowns = [p for p in payloads if p["phase"] == "cooldown"]
    assert [p["pull_index"] for p in cooldowns] == [1, 2]
    assert all(p["pull_count"] == 3 for p in payloads)
    assert [p["state"] for p in payloads if p["state"] != p["previous_state"]] == [
        "arming",
        "running",
        "coastdown",
        "completed",
    ]
    assert run.curve == run.pulls[-1].curve


def test_rf19_thermal_state_is_preserved_between_pulls() -> None:
    """Sem arrefecimento e sem ventilador, a IAT do início da 3.ª puxada sobe ≥ 5 °C."""
    task = make_task()
    request = {
        "run_type": "multi_pull",
        "pull_type": "sweep_pull",
        "pull_count": 3,
        "cooldown_s": 0,
        "fan_on": False,
        "end_rpm": 6300,
    }
    out = run_to_result(task, request, max_s=300.0)
    pulls = out.run.pulls
    assert len(pulls) == 3
    assert pulls[2].curve[0].iat_c >= pulls[0].curve[0].iat_c + 5.0


def test_t031_cooldown_ticks_declare_wall_budget() -> None:
    """Arrefecimento acelerado: ``wall_budget_ticks`` = ``COOLDOWN_SPEEDUP`` só no cooldown.

    O orçamento é só diagnóstico (contagem de overrun no laço): o número de passos por tick
    continua fixo e não depende do relógio de parede.
    """
    from simremap.dyno.runs import COOLDOWN_SPEEDUP

    task = make_task()
    request = {"run_type": "multi_pull", "pull_count": 2, "cooldown_s": 2, "end_rpm": 4000}
    task.handle_command(
        {"type": "run.start", "run_id": "01JAB0000000000000000000T3", "request": request}
    )
    budgets: dict[str, set[int]] = {}
    steps: dict[str, set[int]] = {}
    for _ in range(60_000):
        if task.run is None or not task.run_active:
            break
        phase = task.run.phase
        before = task.tick_index
        task.tick()
        task.drain_outputs()
        budgets.setdefault(phase, set()).add(task.wall_budget_ticks)
        if phase == "cooldown" and task.run is not None and task.run.phase == "cooldown":
            steps.setdefault(phase, set()).add(task.tick_index - before)
    assert budgets["cooldown"] == {COOLDOWN_SPEEDUP}
    assert steps["cooldown"] == {COOLDOWN_SPEEDUP}
    assert all(b == {1} for p, b in budgets.items() if p != "cooldown")
