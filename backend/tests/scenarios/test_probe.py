"""Sonda de margem de knock (T206; scenarios RF-14; dyno RF-26; EC-06)."""

from __future__ import annotations

from typing import Any

import pytest
from scn_env import ScnEnv
from scn_helpers import FakeCalibrations, FakeSimulation, RunSpec, make_log, new_run_id

from simremap.dyno.contracts import DynoRun, DynoRunRequest, RunType
from simremap.scenarios.probe import ProbeFailed, knock_cycles, probe_request, run_probe

SWAP_OK = RunSpec(peak_whp=312.0, egt_max_c=920.0, knock_max_deg=0.0, lambda_wot=0.80)


async def swapped_attempt(scn: ScnEnv, headers: dict[str, str]) -> dict[str, Any]:
    attempt = await scn.start("standalone-swap", headers)
    scn.tune(attempt, SWAP_OK, "swap-ref", profile_id="ft-pro")
    await scn.pull(attempt, run_type="multi_pull", pull_count=3, cooldown_s=0)
    return attempt


async def test_reference_swap_passes_probe_with_same_seed_and_no_damage(scn: ScnEnv) -> None:
    headers = await scn.profile("rodrigo_prep")
    attempt = await swapped_attempt(scn, headers)
    scn.sim.probe_spec = RunSpec(peak_whp=315.0)
    ev = await scn.submit(attempt, headers)
    probe_req = scn.sim.requests[-1]
    assert probe_req.probe is not None
    assert probe_req.probe.ignition_offset_deg == 2.0
    assert probe_req.probe.knock_control_open_loop is True
    assert probe_req.probe.damage_enabled is False
    assert probe_req.run_type == RunType.SWEEP_PULL
    probe_run = scn.sim.runs[next(rid for rid, r in scn.sim.runs.items() if r.request.probe)]
    assert probe_run.seed == attempt["seed"]
    assert probe_run.session_id == attempt["session_id"]
    margin = next(r for r in ev["results"] if r["criterion_id"] == "knock-margin")
    assert margin["passed"] is True
    assert margin["measured"] == 2.0
    assert ev["probe_run_sha256"] == probe_run.curve_sha256
    assert ev["passed"] is True


async def test_plus_three_degrees_fails_with_first_knock_cycle(scn: ScnEnv) -> None:
    headers = await scn.profile("rodrigo_prep")
    attempt = await swapped_attempt(scn, headers)
    scn.sim.probe_spec = RunSpec(peak_whp=318.0, knock_events=((5200.0, 3), (5600.0, 1)))
    ev = await scn.submit(attempt, headers)
    margin = next(r for r in ev["results"] if r["criterion_id"] == "knock-margin")
    assert margin["passed"] is False
    assert margin["score"] == 0.0
    proof = margin["evidence"][0]
    assert proof["cylinder"] == 3
    assert proof["rpm"] == 5200.0
    assert proof["t_sim_s"] is not None
    assert proof["channel"] == "knock_intensity_cyl3"
    assert ev["passed"] is False


async def test_probe_internal_failure_is_error_without_spending_submission(
    scn: ScnEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await scn.profile("rodrigo_prep")
    attempt = await swapped_attempt(scn, headers)
    original = scn.sim.start_run

    async def broken(session_id: str, request: DynoRunRequest) -> DynoRun:
        if request.probe is not None:
            from simremap.core.errors import SimRemapError

            raise SimRemapError("worker morreu", code="SIM_WORKER_UNAVAILABLE")
        return await original(session_id, request)

    monkeypatch.setattr(scn.sim, "start_run", broken)
    ev = await scn.submit(attempt, headers)
    assert ev["status"] == "error"
    assert ev["error_code"] == "PROBE_FAILED"
    got = await scn.attempt(attempt["attempt_id"], headers)
    assert got["state"] == "in_progress"
    assert got["submissions"] == 0


def test_probe_request_from_multi_pull_and_knock_window() -> None:
    src = DynoRunRequest(run_type=RunType.MULTI_PULL, pull_count=3, start_rpm=2500.0)
    req = probe_request(src, 2.0)
    assert req.run_type == RunType.SWEEP_PULL
    assert req.start_rpm == 2500.0
    assert req.probe is not None and req.probe.ignition_offset_deg == 2.0
    run_id = new_run_id()
    log = make_log(
        run_id,
        "s" * 32,
        [RunSpec(knock_events=((1900.0, 1), (4000.0, 2)))],
        DynoRunRequest(run_type=RunType.SWEEP_PULL),
    )
    count, first = knock_cycles(log, 2000.0, 6300.0)
    assert count == 1
    assert first is not None and first.cylinder == 2


async def test_run_probe_timeout_raises() -> None:
    cals = FakeCalibrations()
    sim = FakeSimulation(cals)

    async def slow(*_a: Any, **_k: Any) -> DynoRun:
        raise TimeoutError

    sim.wait_run = slow  # type: ignore[method-assign]
    from simremap.dyno.contracts import SessionCreateRequest

    session = await sim.create_session(
        SessionCreateRequest(
            vehicle_id="hatch-20t-gdi",
            calibration_id="stock-hatch-20t-gdi-oem-stage",
            attempt_id="6c1f0a7e-1d2b-4c3a-9f10-2b3c4d5e6f70",
        )
    )
    src = await sim.start_run(session.session_id, DynoRunRequest(run_type=RunType.SWEEP_PULL))
    with pytest.raises(ProbeFailed):
        await run_probe(sim, session.session_id, src, 2.0, rev_limit_rpm=6500.0)
