"""Avaliador determinístico dos critérios (training-scenarios RF-11 a RF-13; RN-02, RN-15).

``evaluate(scenario, EvaluationInput)`` é uma função pura: usa só os resumos das puxadas de
evidência (``RunSummary``), os ``EvaluationTrace`` a 100 Hz, a calibração congelada e o
resultado da sonda de knock. Nenhum relógio, ``random`` ou estado global entra no cálculo;
o ``evaluation_sha256`` é o SHA-256 do JCS (RFC 8785) da ``Evaluation`` sem
``evaluation_id`` e ``created_at`` (mesmo hash no aluno e no instrutor).

Medidas (seção 8): ``whp`` 0,1; torque 0,1 N·m; retardo de knock 0,01°; EGT 0,1 °C;
lambda 0,001; dispersão 0,01 %; integridade ``floor(1000·min_health)/10`` (aprovada com
``min_health ≥ 0,999`` e 0 ``FailureEvent``, como ``EngineHealth.intact``).

Pontuação por critério (0–100, ``ROUND_HALF_EVEN`` a 0,1): ``ge`` ⇒ ``100·m/T``;
``le`` ⇒ ``100·(1 − (m − T)/B)`` com bandas padrão (EGT 50 °C, knock 3°, dispersão 3 %,
lambda 0,05); booleanos 0/100; integridade = medida; contagem de puxadas
``100·min(1, n/N)``. Total ``Σ w·s / Σ w`` (pesos do cenário). A aprovação exige todos os
critérios ``mandatory``; a pontuação não decide.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import Field

from simremap.core.contracts import ContractModel, Sha256Hex
from simremap.scenarios.contracts import (
    Criterion,
    CriterionKind,
    CriterionResult,
    DefectKind,
    Evaluation,
    Evidence,
    Scenario,
)
from simremap.scenarios.jcs import jcs_sha256
from simremap.scenarios.trace import TRACE_COLUMNS, EvaluationTrace, q

__all__ = [
    "DEFAULT_BANDS",
    "EVALUATOR_VERSION",
    "KIND_COMPARATOR",
    "EvaluationInput",
    "EvidenceRun",
    "KnockCycle",
    "ProbeResult",
    "error_evaluation",
    "evaluate",
    "evaluation_sha256",
    "measure",
    "pending_evaluation",
    "score_criterion",
]

EVALUATOR_VERSION: Final = "1.0.0"
INTEGRITY_MIN_HEALTH: Final = 0.999

KIND_COMPARATOR: Final[dict[CriterionKind, Literal["ge", "le", "bool"]]] = {
    CriterionKind.MIN_WHP: "ge",
    CriterionKind.MIN_DELTA_WHP: "ge",
    CriterionKind.MIN_TORQUE_NM: "ge",
    CriterionKind.MAX_KNOCK_RETARD_DEG: "le",
    CriterionKind.MIN_KNOCK_MARGIN_DEG: "ge",
    CriterionKind.INTEGRITY: "ge",
    CriterionKind.MAX_EGT_C: "le",
    CriterionKind.MAX_EGT_OVERRUN_C: "le",
    CriterionKind.LAMBDA_WOT_MAX: "le",
    CriterionKind.LAMBDA_WOT_MIN: "ge",
    CriterionKind.MIN_POP_EVENTS: "ge",
    CriterionKind.VALID_PULLS: "ge",
    CriterionKind.MAX_SPREAD_PCT: "le",
    CriterionKind.FINAL_PROFILE: "bool",
    CriterionKind.LOCKED_TABLES: "bool",
    CriterionKind.DEFECT_DIAGNOSIS: "bool",
}
"""Comparador obrigatório de cada ``kind`` (outro comparador ⇒ 422 ``SCENARIO_INVALID``)."""

DEFAULT_BANDS: Final[dict[CriterionKind, float]] = {
    CriterionKind.MAX_EGT_C: 50.0,
    CriterionKind.MAX_EGT_OVERRUN_C: 50.0,
    CriterionKind.MAX_KNOCK_RETARD_DEG: 3.0,
    CriterionKind.MAX_SPREAD_PCT: 3.0,
    CriterionKind.LAMBDA_WOT_MAX: 0.05,
}

_COL = {name: i for i, name in enumerate(TRACE_COLUMNS)}


# --------------------------------------------------------------------------- entradas


class KnockCycle(ContractModel):
    """Primeiro ciclo com knock da sonda (evidência do RF-14)."""

    cylinder: int = Field(ge=1, le=8)
    rpm: float = Field(ge=0.0)  # rev/min
    t_sim_s: float = Field(ge=0.0)  # s
    intensity: float = Field(ge=0.0)  # bar de MAPO (intensity_raw)
    knock_class: str = Field(min_length=1, max_length=16)


class ProbeResult(ContractModel):
    """Resultado da sonda de margem de knock (``ProbeOverrides`` do dyno-bench)."""

    run_id: str = Field(min_length=1, max_length=36)
    source_run_id: str = Field(min_length=1, max_length=36)
    ignition_offset_deg: float
    state: str = Field(min_length=1, max_length=24)  # RunState da puxada da sonda
    knock_cycles: int = Field(ge=0)
    first_knock: KnockCycle | None = None
    curve_sha256: Sha256Hex | None = None

    @property
    def passed(self) -> bool:
        return self.state == "completed" and self.knock_cycles == 0


class EvidenceRun(ContractModel):
    """Puxada de evidência válida (resumo + traço)."""

    run_id: str = Field(min_length=1, max_length=36)
    pull_index: int = Field(0, ge=0)
    run_type: str = Field(min_length=1, max_length=24)
    peak_whp: float  # whp (corrigido pela norma do cenário)
    peak_whp_rpm: float  # rev/min
    peak_torque_engine_nm: float  # N·m
    peak_torque_rpm: float  # rev/min
    failures: int = Field(0, ge=0)  # FailureEvent na puxada
    profile_id: str = Field(min_length=1, max_length=16)
    trace: EvaluationTrace


class EvaluationInput(ContractModel):
    """Entrada congelada da avaliação (gravada no ``result_json`` e no pacote)."""

    attempt_id: str = Field(min_length=1, max_length=36)
    submission_index: int = Field(ge=1)
    baseline_peak_whp: float | None = None  # whp
    evidence: list[EvidenceRun] = Field(default_factory=list, max_length=40)
    ignored_runs: list[str] = Field(default_factory=list)
    calibration_content_hash: Sha256Hex | None = None
    locked_tables_changed: list[str] = Field(default_factory=list)
    declared_defect: DefectKind | Literal["none"] | None = None
    probe: ProbeResult | None = None
    hints_revealed: list[int] = Field(default_factory=list)


# --------------------------------------------------------------------------- medidas


@dataclass(frozen=True, slots=True)
class Measure:
    value: float | None
    evidence: tuple[Evidence, ...] = ()
    passed_override: bool | None = None  # integridade, booleanos


def _url(run_id: str) -> str:
    return f"/api/v1/runs/{run_id}/log?format=json"


def _ev(run: EvidenceRun, channel: str, row: Sequence[Any] | None, value: float | None) -> Evidence:
    t = None if row is None else row[_COL["t_sim_s"]]
    rpm = None if row is None else row[_COL["rpm"]]
    return Evidence(
        run_id=run.run_id,
        log_id=run.run_id,
        channel=channel,
        t_sim_s=t,
        rpm=rpm,
        value=value,
        url=_url(run.run_id),
    )


def _extreme(
    runs: Sequence[EvidenceRun],
    column: str,
    *,
    largest: bool,
    where: Callable[[Sequence[Any]], bool] | None = None,
) -> tuple[float | None, EvidenceRun | None, Sequence[Any] | None]:
    best: float | None = None
    best_run: EvidenceRun | None = None
    best_row: Sequence[Any] | None = None
    i = _COL[column]
    for run in runs:
        for row in run.trace.rows:
            value = row[i]
            if value is None or (where is not None and not where(row)):
                continue
            if best is None or (value > best if largest else value < best):
                best, best_run, best_row = float(value), run, row
    return best, best_run, best_row


def _wot(min_rpm: float) -> Callable[[Sequence[Any]], bool]:
    def check(row: Sequence[Any]) -> bool:
        pedal = row[_COL["pedal_pct"]]
        rpm = row[_COL["rpm"]]
        return pedal is not None and rpm is not None and pedal >= 90.0 and rpm >= min_rpm  # noqa: PLR2004 - pedal ≥ 90 % (spec)

    return check


def _overrun(row: Sequence[Any]) -> bool:
    return bool(row[_COL["overrun_active"]])


def _whp(runs: Sequence[EvidenceRun]) -> list[tuple[float, EvidenceRun]]:
    return [(float(q(r.peak_whp, 1) or 0.0), r) for r in runs]


def _peak_evidence(run: EvidenceRun, channel: str, rpm: float, value: float) -> Evidence:
    return Evidence(
        run_id=run.run_id,
        log_id=run.run_id,
        channel=channel,
        rpm=rpm,
        value=value,
        url=_url(run.run_id),
    )


def _integrity(runs: Sequence[EvidenceRun]) -> Measure:
    worst, worst_run, worst_row = _extreme(runs, "health_min_pct", largest=False)
    if worst is None or worst_run is None:
        return Measure(None)
    pct = math.floor(1000.0 * (worst / 100.0) + 1e-9) / 10.0
    failures = sum(r.failures for r in runs)
    ok = worst / 100.0 >= INTEGRITY_MIN_HEALTH - 1e-12 and failures == 0
    return Measure(
        pct, (_ev(worst_run, "health_min_pct", worst_row, q(worst, 3)),), passed_override=ok
    )


def _spread(runs: Sequence[EvidenceRun]) -> Measure:
    values = _whp(runs)
    if not values:
        return Measure(None)
    peaks = [v for v, _ in values]
    mean = sum(peaks) / len(peaks)
    spread = 0.0 if mean <= 0 else 100.0 * (max(peaks) - min(peaks)) / mean
    hi = max(values, key=lambda x: x[0])
    return Measure(q(spread, 2), (_peak_evidence(hi[1], "whp", hi[1].peak_whp_rpm, hi[0]),))


def _pops(runs: Sequence[EvidenceRun]) -> Measure:
    if not runs:
        return Measure(None)
    per_run = []
    for run in runs:
        total = sum(int(r[_COL["pop_events"]]) for r in run.trace.rows if _overrun(r))
        per_run.append((total, run))
    low = min(per_run, key=lambda x: x[0])
    return Measure(float(low[0]), (_ev(low[1], "overrun_afterfire", None, float(low[0])),))


def measure(  # noqa: PLR0911, PLR0912 - um ramo por kind
    criterion: Criterion,
    scenario: Scenario,
    inp: EvaluationInput,
) -> Measure:
    """Valor medido de um critério (``None`` quando não há dados)."""
    runs = inp.evidence
    kind = criterion.kind
    if kind == CriterionKind.VALID_PULLS:
        return Measure(float(len(runs)))
    if kind in (CriterionKind.MIN_WHP, CriterionKind.MIN_DELTA_WHP):
        values = _whp(runs)
        if not values:
            return Measure(None)
        low, run = min(values, key=lambda x: x[0])
        ev = (_peak_evidence(run, "whp", run.peak_whp_rpm, low),)
        if kind == CriterionKind.MIN_WHP:
            return Measure(low, ev)
        if inp.baseline_peak_whp is None:
            return Measure(None, ev)
        return Measure(q(low - float(q(inp.baseline_peak_whp, 1) or 0.0), 1), ev)
    if kind == CriterionKind.MIN_TORQUE_NM:
        if not runs:
            return Measure(None)
        run = min(runs, key=lambda r: q(r.peak_torque_engine_nm, 1) or 0.0)
        value = q(run.peak_torque_engine_nm, 1)
        return Measure(
            value, (_peak_evidence(run, "torque_nm", run.peak_torque_rpm, value or 0.0),)
        )
    if kind == CriterionKind.MAX_KNOCK_RETARD_DEG:
        value, worst, row = _extreme(runs, "knock_retard_max_deg", largest=True)
        if worst is None:
            return Measure(None)
        return Measure(q(value, 2), (_ev(worst, "knock_retard_deg", row, q(value, 2)),))
    if kind in (CriterionKind.MAX_EGT_C, CriterionKind.MAX_EGT_OVERRUN_C):
        where = _overrun if kind == CriterionKind.MAX_EGT_OVERRUN_C else None
        value, hottest, row = _extreme(runs, "egt_collector_c", largest=True, where=where)
        if hottest is None:
            return Measure(None)
        return Measure(q(value, 1), (_ev(hottest, "egt_collector_c", row, q(value, 1)),))
    if kind in (CriterionKind.LAMBDA_WOT_MAX, CriterionKind.LAMBDA_WOT_MIN):
        largest = kind == CriterionKind.LAMBDA_WOT_MAX
        column = "lambda_max" if largest else "lambda_min"
        value, found, row = _extreme(
            runs, column, largest=largest, where=_wot(scenario.criteria.lambda_window_min_rpm)
        )
        if found is None:
            return Measure(None)
        return Measure(q(value, 3), (_ev(found, "lambda_measured", row, q(value, 3)),))
    if kind == CriterionKind.MIN_POP_EVENTS:
        return _pops(runs)
    if kind == CriterionKind.INTEGRITY:
        return _integrity(runs)
    if kind == CriterionKind.MAX_SPREAD_PCT:
        return _spread(runs)
    if kind == CriterionKind.MIN_KNOCK_MARGIN_DEG:
        return _knock_margin(criterion, inp)
    if kind == CriterionKind.FINAL_PROFILE:
        allowed = scenario.constraints.allowed_final_profiles
        ok = bool(runs) and (not allowed or all(r.profile_id in allowed for r in runs))
        return Measure(1.0 if ok else 0.0, passed_override=ok)
    if kind == CriterionKind.LOCKED_TABLES:
        locked = set(scenario.constraints.locked_table_ids)
        ok = not (locked & set(inp.locked_tables_changed))
        return Measure(1.0 if ok else 0.0, passed_override=ok)
    defect = scenario.hidden_defect
    ok = defect is not None and inp.declared_defect == defect.kind.value
    return Measure(1.0 if ok else 0.0, passed_override=ok)


def _knock_margin(criterion: Criterion, inp: EvaluationInput) -> Measure:
    probe = inp.probe
    if probe is None:
        return Measure(None)
    if probe.passed:
        return Measure(q(probe.ignition_offset_deg, 2), passed_override=True)
    knock = probe.first_knock
    evidence: tuple[Evidence, ...] = ()
    if knock is not None:
        evidence = (
            Evidence(
                run_id=probe.run_id,
                log_id=probe.run_id,
                channel=f"knock_intensity_cyl{knock.cylinder}",
                t_sim_s=q(knock.t_sim_s, 3),
                rpm=q(knock.rpm, 1),
                cylinder=knock.cylinder,
                value=q(knock.intensity, 3),
                url=_url(probe.run_id),
            ),
        )
    return Measure(0.0, evidence, passed_override=False)


# --------------------------------------------------------------------------- pontuação


def _band(criterion: Criterion) -> float:
    if criterion.band is not None:
        return float(criterion.band)
    default = DEFAULT_BANDS.get(criterion.kind)
    if default is not None:
        return default
    return max(abs(float(criterion.threshold or 0.0)) * 0.1, 1e-6)


def score_criterion(  # noqa: PLR0911 - um ramo por regra de pontuação
    criterion: Criterion, m: Measure, scenario: Scenario
) -> tuple[bool, float]:
    """``(aprovado, pontuação 0–100)`` de um critério para a medida ``m``."""
    value = m.value
    kind = criterion.kind
    if value is None:
        return False, 0.0
    if kind == CriterionKind.INTEGRITY:
        threshold = float(criterion.threshold or 100.0)
        ok = bool(m.passed_override) and value >= threshold - 0.1 - 1e-9
        return ok, max(0.0, min(100.0, value))
    if kind == CriterionKind.VALID_PULLS:
        target = float(criterion.threshold or scenario.criteria.required_valid_pulls)
        ok = value >= target
        return ok, 100.0 * min(1.0, value / target) if target > 0 else 100.0
    if criterion.comparator == "bool" or m.passed_override is not None:
        ok = bool(m.passed_override)
        if kind == CriterionKind.MIN_KNOCK_MARGIN_DEG:
            ok = ok and value >= float(criterion.threshold or 0.0) - 1e-9
        return ok, 100.0 if ok else 0.0
    threshold = float(criterion.threshold or 0.0)
    if criterion.comparator == "ge":
        if value >= threshold:
            return True, 100.0
        return False, 0.0 if threshold <= 0 else max(0.0, 100.0 * value / threshold)
    if value <= threshold:
        return True, 100.0
    return False, max(0.0, 100.0 * (1.0 - (value - threshold) / _band(criterion)))


def _criterion_result(
    criterion: Criterion, scenario: Scenario, inp: EvaluationInput
) -> CriterionResult:
    m = measure(criterion, scenario, inp)
    ok, score = score_criterion(criterion, m, scenario)
    return CriterionResult(
        criterion_id=criterion.criterion_id,
        kind=criterion.kind,
        comparator=criterion.comparator,
        measured=m.value,
        threshold=criterion.threshold,
        passed=ok,
        score=float(q(score, 1) or 0.0),
        weight=criterion.weight,
        mandatory=criterion.mandatory,
        evidence=list(m.evidence[:10]),
    )


def criterion_results(scenario: Scenario, inp: EvaluationInput) -> list[CriterionResult]:
    """Resultado por critério na ordem do cenário (também usado no progresso provisório)."""
    return [_criterion_result(c, scenario, inp) for c in scenario.criteria.criteria]


def evaluation_sha256(evaluation: Evaluation) -> str:
    return jcs_sha256(evaluation.hashable_content())


def _unique(items: Sequence[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


def evaluate(
    scenario: Scenario,
    inp: EvaluationInput,
    *,
    evaluation_id: str,
    created_at: datetime | None = None,
) -> Evaluation:
    """Avaliação ``completed`` com ``evaluation_sha256`` (função pura de ``scenario`` e ``inp``)."""
    results = criterion_results(scenario, inp)
    weights = sum(r.weight for r in results)
    total = sum(r.weight * r.score for r in results) / weights if weights > 0 else 0.0
    passed = all(r.passed for r in results if r.mandatory)
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        attempt_id=inp.attempt_id,
        submission_index=inp.submission_index,
        status="completed",
        evaluator_version=EVALUATOR_VERSION,
        passed=passed,
        total_score=float(q(min(100.0, max(0.0, total)), 1) or 0.0),
        results=results,
        evidence_run_ids=_unique([r.run_id for r in inp.evidence]),
        ignored_runs=list(inp.ignored_runs),
        calibration_content_hash=inp.calibration_content_hash,
        probe_run_sha256=None if inp.probe is None else inp.probe.curve_sha256,
        hints_revealed=sorted(inp.hints_revealed),
        revealed_defect=scenario.hidden_defect,
        created_at=created_at,
    )
    return evaluation.model_copy(update={"evaluation_sha256": evaluation_sha256(evaluation)})


def pending_evaluation(
    attempt_id: str, submission_index: int, *, evaluation_id: str, created_at: datetime
) -> Evaluation:
    return Evaluation(
        evaluation_id=evaluation_id,
        attempt_id=attempt_id,
        submission_index=submission_index,
        status="pending",
        evaluator_version=EVALUATOR_VERSION,
        created_at=created_at,
    )


def error_evaluation(
    attempt_id: str,
    submission_index: int,
    code: str,
    *,
    evaluation_id: str,
    created_at: datetime,
    hints_revealed: Sequence[int] = (),
) -> Evaluation:
    return Evaluation(
        evaluation_id=evaluation_id,
        attempt_id=attempt_id,
        submission_index=submission_index,
        status="error",
        error_code=code,
        evaluator_version=EVALUATOR_VERSION,
        hints_revealed=sorted(hints_revealed),
        created_at=created_at,
    )
