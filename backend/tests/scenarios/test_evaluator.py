"""Avaliador determinístico (T205; scenarios RF-10 a RF-13; RN-15; G-01; EC-11)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest
from scn_helpers import RunSpec, make_log, new_run_id

from simremap.dyno.contracts import DynoRunRequest, RunType
from simremap.scenarios.catalog import builtin_documents
from simremap.scenarios.contracts import Scenario
from simremap.scenarios.evaluator import (
    EvaluationInput,
    EvidenceRun,
    evaluate,
    measure,
    score_criterion,
)
from simremap.scenarios.trace import build_trace

STAGE1_PASS = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5, lambda_wot=0.82)
EVAL_ID = "0f5e9c2a-6c1f-4a7e-9d2b-4c3a9f102b3c"
ATTEMPT_ID = "6c1f0a7e-1d2b-4c3a-9f10-2b3c4d5e6f70"


def stage1() -> Scenario:
    doc = builtin_documents()["stage1-oem"]
    doc["initial_calibration"]["content_hash"] = "a" * 64
    return Scenario.model_validate(doc)


def evidence(spec: RunSpec, *, pull_index: int = 0, profile_id: str = "oem-stage") -> EvidenceRun:
    run_id = new_run_id()
    req = DynoRunRequest(run_type=RunType.SWEEP_PULL)
    log = make_log(run_id, "s" * 32, [spec], req)
    return EvidenceRun(
        run_id=run_id,
        pull_index=pull_index,
        run_type="sweep_pull",
        peak_whp=spec.peak_whp,
        peak_whp_rpm=6000.0,
        peak_torque_engine_nm=spec.peak_torque_nm,
        peak_torque_rpm=3500.0,
        failures=1 if spec.failure else 0,
        profile_id=profile_id,
        trace=build_trace(log, run_id=run_id, pedal_pct=100.0),
    )


def inp(runs: list[EvidenceRun], **over: Any) -> EvaluationInput:
    data: dict[str, Any] = {
        "attempt_id": ATTEMPT_ID,
        "submission_index": 1,
        "baseline_peak_whp": 220.0,
        "evidence": runs,
        "calibration_content_hash": "f" * 64,
    }
    data.update(over)
    return EvaluationInput(**data)


def result(evaluation: Any, criterion_id: str) -> Any:
    return next(r for r in evaluation.results if r.criterion_id == criterion_id)


def test_stage1_reference_solution_passes_and_initial_fails() -> None:
    runs = [evidence(STAGE1_PASS), evidence(STAGE1_PASS)]
    ok = evaluate(stage1(), inp(runs), evaluation_id=EVAL_ID)
    assert ok.passed is True
    assert ok.total_score == 100.0
    assert result(ok, "delta-whp").measured == 42.0
    stock = RunSpec(peak_whp=220.0, egt_max_c=900.0, knock_max_deg=0.5)
    bad = evaluate(stage1(), inp([evidence(stock), evidence(stock)]), evaluation_id=EVAL_ID)
    assert bad.passed is False
    assert result(bad, "delta-whp").passed is False
    assert result(bad, "delta-whp").score == 0.0


def test_egt_962_at_6100_rpm_fails_with_evidence() -> None:
    hot = RunSpec(peak_whp=262.0, egt_max_c=962.0, egt_peak_rpm=6100.0)
    ev = evaluate(stage1(), inp([evidence(hot), evidence(STAGE1_PASS)]), evaluation_id=EVAL_ID)
    egt = result(ev, "egt")
    assert egt.passed is False
    assert egt.measured == 962.0
    assert len(egt.evidence) == 1
    proof = egt.evidence[0]
    assert proof.channel == "egt_collector_c"
    assert proof.rpm is not None and abs(proof.rpm - 6100.0) <= 25.0
    assert proof.url == f"/api/v1/runs/{proof.run_id}/log?format=json"
    # le com banda padrão de 50 °C: 100·(1 − 12/50) = 76.
    assert egt.score == 76.0
    assert ev.passed is False


def test_mandatory_failure_beats_total_score_95() -> None:
    doc = builtin_documents()["stage1-oem"]
    doc["initial_calibration"]["content_hash"] = "a" * 64
    doc["criteria"]["criteria"] = [
        c
        for c in doc["criteria"]["criteria"]
        if c["criterion_id"] not in ("final-profile", "lambda-min")
    ]
    for c in doc["criteria"]["criteria"]:
        c["weight"] = 1.0
    scenario = Scenario.model_validate(doc)
    assert len(scenario.criteria.criteria) == 7
    knocky = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=4.05)
    ev = evaluate(scenario, inp([evidence(knocky), evidence(STAGE1_PASS)]), evaluation_id=EVAL_ID)
    passed = [r for r in ev.results if r.passed]
    assert len(passed) == 6
    assert result(ev, "knock").measured == 4.05
    assert result(ev, "knock").score == 65.0
    assert ev.total_score == 95.0
    assert ev.passed is False


def test_same_input_same_hash_20_times_and_no_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = [evidence(STAGE1_PASS), evidence(STAGE1_PASS)]
    data = inp(runs)
    first = evaluate(stage1(), data, evaluation_id=EVAL_ID)
    hashes = {
        evaluate(
            stage1(),
            EvaluationInput.model_validate(data.model_dump(mode="json")),
            evaluation_id=EVAL_ID,
        ).evaluation_sha256
        for _ in range(20)
    }
    assert hashes == {first.evaluation_sha256}

    def forbidden() -> float:
        raise AssertionError("o avaliador leu o relógio")

    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(time, "monotonic", forbidden)
    frozen = evaluate(
        stage1(), data, evaluation_id=EVAL_ID, created_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    later = evaluate(
        stage1(), data, evaluation_id="1" * 32, created_at=datetime(2030, 1, 1, tzinfo=UTC)
    )
    assert frozen.evaluation_sha256 == later.evaluation_sha256 == first.evaluation_sha256


def test_integrity_threshold_0999_and_failures() -> None:
    worn = RunSpec(peak_whp=262.0, health_end_pct=99.95)
    ok = evaluate(stage1(), inp([evidence(worn), evidence(STAGE1_PASS)]), evaluation_id=EVAL_ID)
    assert result(ok, "integrity").passed is True
    assert result(ok, "integrity").measured == 99.9
    broken = RunSpec(peak_whp=262.0, health_end_pct=99.85)
    bad = evaluate(stage1(), inp([evidence(broken), evidence(STAGE1_PASS)]), evaluation_id=EVAL_ID)
    integ = result(bad, "integrity")
    assert integ.passed is False
    assert integ.score == integ.measured == 99.8
    assert integ.evidence[0].channel == "health_min_pct"
    failed = RunSpec(peak_whp=262.0, failure=True)
    with_failure = evaluate(
        stage1(), inp([evidence(failed), evidence(STAGE1_PASS)]), evaluation_id=EVAL_ID
    )
    assert result(with_failure, "integrity").passed is False


def test_no_valid_pulls_ec11() -> None:
    ev = evaluate(
        stage1(), inp([], ignored_runs=["01JX:calibration_not_submitted"]), evaluation_id=EVAL_ID
    )
    pulls = result(ev, "pulls")
    assert pulls.measured == 0.0
    assert pulls.passed is False
    assert ev.passed is False
    assert ev.ignored_runs == ["01JX:calibration_not_submitted"]
    assert all(
        r.measured is None
        for r in ev.results
        if r.kind.value not in ("valid_pulls", "final_profile")
    )


def test_lambda_spread_pops_and_scores() -> None:
    doc = builtin_documents()["stage2-pops-bangs"]
    doc["initial_calibration"]["content_hash"] = "a" * 64
    scenario = Scenario.model_validate(doc)
    pops = RunSpec(peak_whp=290.0, pops=6, egt_overrun_c=900.0, lambda_wot=0.86)
    few = RunSpec(peak_whp=280.0, pops=3, egt_overrun_c=990.0, lambda_wot=0.70)
    ev = evaluate(scenario, inp([evidence(pops), evidence(few)]), evaluation_id=EVAL_ID)
    assert result(ev, "pops").measured == 3.0
    assert result(ev, "pops").score == 60.0
    assert result(ev, "egt-overrun").measured == 990.0
    assert result(ev, "egt-overrun").passed is False
    assert result(ev, "lambda-min").measured == 0.7
    assert result(ev, "lambda-max").measured == 0.86
    assert result(ev, "spread").measured == round(100 * 10 / 285, 2)
    assert result(ev, "spread").passed is False
    assert result(ev, "delta-whp").measured == 60.0


def test_score_rules_unit() -> None:
    scenario = stage1()
    crit = next(c for c in scenario.criteria.criteria if c.criterion_id == "delta-whp")
    from simremap.scenarios.evaluator import Measure

    assert score_criterion(crit, Measure(20.0), scenario) == (False, 50.0)
    assert score_criterion(crit, Measure(None), scenario) == (False, 0.0)
    final = next(c for c in scenario.criteria.criteria if c.kind.value == "final_profile")
    runs = [evidence(STAGE1_PASS, profile_id="ft-pro")]
    m = measure(final, scenario, inp(runs))
    assert m.passed_override is False


def test_trace_uses_logged_pedal_channel_when_present() -> None:
    """``pedal_pct`` do DataLog (pedal real da bancada) substitui o pedal do pedido."""
    import numpy as np

    from simremap.telemetry.channels import build_catalog
    from simremap.telemetry.datalog import LogData

    run_id = new_run_id()
    log = make_log(run_id, "s" * 32, [STAGE1_PASS], DynoRunRequest(run_type=RunType.SWEEP_PULL))
    n = log.header.n_samples
    pedal = np.linspace(0.0, 100.0, n, dtype=np.float32)  # rampa: só o fim fica ≥ 90 %
    pedal_channel = build_catalog(4, True).get("pedal_pct")
    assert pedal_channel is not None
    header = log.header.model_copy(update={"channels": [*log.header.channels, pedal_channel]})
    with_pedal = LogData.build(header, log.t_sim_s, np.vstack([log.columns, pedal[None, :]]))
    logged = build_trace(with_pedal, run_id=run_id, pedal_pct=100.0)
    assumed = build_trace(log, run_id=run_id, pedal_pct=100.0)
    col = logged.columns.index("pedal_pct")
    assert logged.rows[0][col] < 5.0 and logged.rows[-1][col] > 95.0
    assert max(r[col] for r in assumed.rows) == 100.0
    assert [r[col] for r in logged.rows] != [r[col] for r in assumed.rows]
