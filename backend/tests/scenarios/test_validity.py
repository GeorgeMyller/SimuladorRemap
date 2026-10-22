"""Regras de validade das puxadas (T204; scenarios RF-09, V-01 a V-07)."""

from __future__ import annotations

from typing import Any

from scn_env import ScnEnv
from scn_helpers import SIM_HZ, RunSpec

from simremap.dyno.contracts import AbortReason, RunState
from simremap.scenarios.ports import CalibrationApply

GOOD = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5)


def by_run(attempt: dict[str, Any], run_id: str, pull_index: int = 0) -> dict[str, Any]:
    return next(
        r for r in attempt["runs"] if r["run_id"] == run_id and r["pull_index"] == pull_index
    )


async def test_calibration_changed_mid_run_is_invalid(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD)
    run_id = await scn.pull(attempt)
    run = scn.sim.runs[run_id]
    mid = (run.started_at_tick + (run.ended_at_tick or 0)) / 2 / SIM_HZ
    scn.services.audit.record(
        attempt["session_id"],
        CalibrationApply(t_sim_s=mid, calibration_id="outra", content_hash="9" * 64),
    )
    got = await scn.attempt(attempt["attempt_id"], headers)
    row = by_run(got, run_id)
    assert row["valid"] is False
    assert row["invalid_reason"] == "calibration_changed_during_run"


async def test_terminal_states_and_request_rules(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD)
    scn.sim.queue.append([RunSpec(state=RunState.ABORTED, abort_reason=AbortReason.EGT_LIMIT)])
    aborted = await scn.pull(attempt)
    scn.sim.queue.append([RunSpec(state=RunState.ENGINE_FAILED, failure=True)])
    failed = await scn.pull(attempt)
    gear = await scn.pull(attempt, gear=3)
    short = await scn.pull(attempt, end_rpm=5000.0)
    hold = await scn.pull(
        attempt, run_type="steady_state_hold", cells=[{"rpm": 3000, "pedal_pct": 100}]
    )
    good = await scn.pull(attempt)
    got = await scn.attempt(attempt["attempt_id"], headers)
    assert by_run(got, aborted)["invalid_reason"] == "run_not_completed"
    assert by_run(got, failed)["invalid_reason"] == "engine_failed"
    assert by_run(got, gear)["invalid_reason"] == "gear_mismatch"
    assert by_run(got, short)["invalid_reason"] == "end_rpm_too_low"
    assert by_run(got, hold)["invalid_reason"] == "run_type_not_allowed"
    assert by_run(got, good)["valid"] is True
    # Progresso provisório com o hash atual: a puxada válida conta 1 de 2.
    pulls = next(p for p in got["progress"] if p["criterion_id"] == "pulls")
    assert pulls["measured"] == 1.0


async def test_probe_runs_are_not_attempt_runs_and_trace_unavailable(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD)
    probe = await scn.pull(
        attempt, probe={"ignition_offset_deg": 2.0, "knock_control_open_loop": True}
    )
    lost = await scn.pull(attempt)
    scn.sim.fail_logs.add(lost)
    got = await scn.attempt(attempt["attempt_id"], headers)
    ids = {r["run_id"] for r in got["runs"]}
    assert probe not in ids
    assert by_run(got, lost)["invalid_reason"] == "trace_unavailable"
    scn.sim.fail_logs.clear()
    again = await scn.attempt(attempt["attempt_id"], headers)
    assert by_run(again, lost)["valid"] is True


async def test_multi_pull_counts_one_by_one_and_profile_rule(scn: ScnEnv) -> None:
    headers = await scn.profile("rodrigo_prep")
    attempt = await scn.start("standalone-swap", headers)
    # Sem swap, o perfil da sessão continua oem-stage ⇒ profile_not_allowed.
    scn.tune(attempt, RunSpec(peak_whp=310.0))
    oem = await scn.pull(attempt, run_type="multi_pull", pull_count=3, cooldown_s=0)
    scn.tune(attempt, RunSpec(peak_whp=310.0), "swap", profile_id="ft-pro")
    multi = await scn.pull(attempt, run_type="multi_pull", pull_count=3, cooldown_s=0)
    got = await scn.attempt(attempt["attempt_id"], headers)
    assert by_run(got, oem, 1)["invalid_reason"] == "profile_not_allowed"
    rows = [r for r in got["runs"] if r["run_id"] == multi]
    assert [r["pull_index"] for r in rows] == [1, 2, 3]
    assert all(r["valid"] for r in rows)
    # baseline_pull fora de allowed_run_types (só multi_pull) no standalone-swap.
    assert by_run(got, got["baseline_run_id"])["invalid_reason"] == "run_type_not_allowed"


async def test_submitted_hash_rule_on_submit(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD, "v2")
    old_a = await scn.pull(attempt)
    old_b = await scn.pull(attempt)
    scn.tune(attempt, GOOD, "v3")
    ev = await scn.submit(attempt, headers)
    assert ev["status"] == "completed"
    assert ev["passed"] is False
    assert f"{old_a}:calibration_not_submitted" in ev["ignored_runs"]
    assert f"{old_b}:calibration_not_submitted" in ev["ignored_runs"]
    assert next(r for r in ev["results"] if r["criterion_id"] == "pulls")["measured"] == 0.0
