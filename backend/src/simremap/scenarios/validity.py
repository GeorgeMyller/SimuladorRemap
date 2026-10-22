"""Regras de puxada válida V-01 a V-07 (training-scenarios RF-09, seção 8).

``classify`` é uma função pura: recebe a puxada (``DynoRun``), a sessão, o cenário, a
tentativa e o histórico de calibrações aplicadas durante a puxada, e devolve um
``RunVerdict`` por puxada (uma por ``pull_index`` em ``multi_pull``) com o primeiro motivo
de recusa, pela ordem das regras:

- V-01 ``run_not_completed`` / ``engine_failed`` — estado diferente de ``completed``;
- V-02 ``run_type_not_allowed`` — fora de ``constraints.allowed_run_types``;
- V-03 ``calibration_changed_during_run`` (2 ou mais ``calibration_hash`` na puxada) e
  ``calibration_not_submitted`` (hash diferente do submetido; só com ``submitted_hash``);
- V-04 ``session_conditions_mismatch`` — combustível, ambiente, norma ou ``seed``;
- V-05 ``damage_disabled`` / ``physics_faults_mismatch`` (sondas: ``probe_run``);
- V-06 ``end_rpm_too_low`` / ``gear_mismatch``;
- V-07 ``profile_not_allowed`` — perfil da sessão na puxada fora de
  ``constraints.allowed_final_profiles``;
- ``trace_unavailable`` — log ilegível depois das novas tentativas (EC-04).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from simremap.dyno.contracts import DynoRun, RunState, RunType, SimulationSession
from simremap.physics.contracts import PhysicsFault
from simremap.scenarios.contracts import Scenario

__all__ = [
    "INVALID_REASONS",
    "RunContext",
    "RunVerdict",
    "classify",
    "expected_faults",
    "min_end_rpm",
]

INVALID_REASONS: Final[tuple[str, ...]] = (
    "run_not_completed",
    "engine_failed",
    "run_type_not_allowed",
    "calibration_changed_during_run",
    "calibration_not_submitted",
    "session_conditions_mismatch",
    "damage_disabled",
    "physics_faults_mismatch",
    "probe_run",
    "end_rpm_too_low",
    "gear_mismatch",
    "profile_not_allowed",
    "trace_unavailable",
)


@dataclass(frozen=True, slots=True)
class RunContext:
    """Dados da sessão e do histórico de calibração necessários à classificação."""

    session: SimulationSession
    seed: int
    rev_limit_rpm: float
    profile_id: str  # perfil da sessão durante a puxada (cabeçalho do log ou sessão)
    calibration_hashes: frozenset[str] = frozenset()  # aplicados a meio da puxada
    trace_available: bool = True


@dataclass(frozen=True, slots=True)
class RunVerdict:
    run_id: str
    run_type: str
    pull_index: int
    valid: bool
    invalid_reason: str | None
    calibration_hash: str
    peak_whp: float | None
    hashes: frozenset[str] = field(default_factory=frozenset)


def expected_faults(scenario: Scenario) -> list[PhysicsFault]:
    """Falhas físicas derivadas do ``HiddenDefect`` (RF-08)."""
    return [] if scenario.hidden_defect is None else [scenario.hidden_defect.to_physics_fault()]


def min_end_rpm(scenario: Scenario, rev_limit_rpm: float) -> float:
    """``criteria.min_end_rpm`` (padrão ``rev_limit_rpm − 500``)."""
    value = scenario.criteria.min_end_rpm
    return rev_limit_rpm - 500.0 if value is None else float(value)


def _session_reason(scenario: Scenario, ctx: RunContext, run: DynoRun) -> str | None:
    s = ctx.session
    if (
        s.fuel_id != scenario.fuel_id
        or s.ambient != scenario.ambient
        or s.correction_standard != scenario.correction_standard
        or s.seed != ctx.seed
        or run.seed != ctx.seed
    ):
        return "session_conditions_mismatch"
    if run.request.probe is not None:
        return "probe_run"
    if not s.damage_enabled:
        return "damage_disabled"
    faults = [f.model_dump(mode="json") for f in s.physics_faults]
    if faults != [f.model_dump(mode="json") for f in expected_faults(scenario)]:
        return "physics_faults_mismatch"
    return None


def _common_reason(  # noqa: PLR0911 - uma regra V-0x por retorno
    scenario: Scenario, ctx: RunContext, run: DynoRun, submitted_hash: str | None
) -> str | None:
    cons = scenario.constraints
    if run.run_type.value not in cons.allowed_run_types:
        return "run_type_not_allowed"
    hashes = {run.calibration_hash, *ctx.calibration_hashes}
    if len(hashes) > 1:
        return "calibration_changed_during_run"
    if submitted_hash is not None and run.calibration_hash != submitted_hash:
        return "calibration_not_submitted"
    reason = _session_reason(scenario, ctx, run)
    if reason is not None:
        return reason
    if (
        run.request.effective_end_rpm(ctx.rev_limit_rpm)
        < min_end_rpm(scenario, ctx.rev_limit_rpm) - 1e-9
    ):
        return "end_rpm_too_low"
    if run.request.gear != cons.gear:
        return "gear_mismatch"
    allowed = cons.allowed_final_profiles
    if allowed and ctx.profile_id not in allowed:
        return "profile_not_allowed"
    if not ctx.trace_available:
        return "trace_unavailable"
    return None


def _state_reason(state: RunState) -> str | None:
    if state == RunState.COMPLETED:
        return None
    return "engine_failed" if state == RunState.ENGINE_FAILED else "run_not_completed"


def classify(
    run: DynoRun,
    scenario: Scenario,
    ctx: RunContext,
    *,
    submitted_hash: str | None = None,
) -> list[RunVerdict]:
    """Veredictos da puxada (``multi_pull``: um por puxada, ``pull_index`` 1..n)."""
    common = _common_reason(scenario, ctx, run, submitted_hash)
    hashes = frozenset({run.calibration_hash, *ctx.calibration_hashes})
    if run.run_type == RunType.MULTI_PULL and run.pulls:
        verdicts: list[RunVerdict] = []
        for pull in run.pulls:
            index = pull.pull_index if pull.pull_index > 0 else len(verdicts) + 1
            reason = _state_reason(pull.state) or common
            verdicts.append(
                RunVerdict(
                    run_id=run.run_id,
                    run_type=run.run_type.value,
                    pull_index=index,
                    valid=reason is None,
                    invalid_reason=reason,
                    calibration_hash=run.calibration_hash,
                    peak_whp=pull.summary.peak_whp,
                    hashes=hashes,
                )
            )
        return verdicts
    reason = _state_reason(run.state) or common
    return [
        RunVerdict(
            run_id=run.run_id,
            run_type=run.run_type.value,
            pull_index=0,
            valid=reason is None,
            invalid_reason=reason,
            calibration_hash=run.calibration_hash,
            peak_whp=None if run.summary is None else run.summary.peak_whp,
            hashes=hashes,
        )
    ]
