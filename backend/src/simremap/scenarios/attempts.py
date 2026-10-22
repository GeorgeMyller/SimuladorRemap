"""Ciclo de vida das tentativas (training-scenarios RF-07 a RF-10, RF-15, RF-16, RF-27;
EC-04 a EC-06, EC-11 a EC-13, EC-15).

Estados: ``preparing`` → ``in_progress`` | ``failed_to_start``; ``in_progress`` →
``evaluating`` | ``abandoned`` | ``expired``; ``evaluating`` → ``passed`` |
``in_progress`` | ``failed_final``. Terminais encerram a sessão do dinamômetro.

1. Início (E-36): abandona a tentativa aberta do mesmo perfil e cenário (RF-27), clona a
   calibração inicial no ecu-core (``content_hash`` tem de ser o do cenário, senão 422
   ``SCENARIO_CALIBRATION_HASH_MISMATCH``; num builtin com ``vehicle_stock`` há autocura:
   cópia da fábrica do catálogo ou ressincronização do hash do cenário, D-02), cria a
   ``SimulationSession`` com veículo, perfil, combustível, ambiente, ``seed`` (derivada do
   ``attempt_id`` sem ``seed`` no cenário), ``physics_faults`` do ``HiddenDefect`` e
   ``attempt_id``, e corre a ``baseline_pull`` em segundo plano (120 s; falha ⇒
   ``failed_to_start`` com ``BASELINE_FAILED``).
2. Classificação (RF-09): cada puxada terminal da sessão (menos as sondas) recebe o
   ``EvaluationTrace`` (log lido com 3 novas tentativas 200/400/800 ms) e o veredicto
   V-01..V-07; o ``content_hash`` aplicado a meio da puxada vem da ``CalibrationAudit``.
3. Submissão (E-41): congela a última versão da calibração, escolhe as puxadas de
   evidência (``run_ids`` ou as últimas ``required_valid_pulls`` válidas com o hash
   submetido), corre a sonda de knock quando há ``min_knock_margin_deg`` e avalia em
   segundo plano. ``TRACE_UNAVAILABLE``/``PROBE_FAILED`` não gastam submissão.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.db.base import utcnow
from simremap.db.models.scenarios import AttemptRow, AttemptRunRow, EvaluationRow
from simremap.dyno.contracts import (
    TERMINAL_RUN_STATES,
    AbortReason,
    DynoRun,
    DynoRunRequest,
    RunState,
    RunType,
    SessionCreateRequest,
)
from simremap.scenarios.catalog import ScenarioCatalog, VehicleInfo
from simremap.scenarios.contracts import (
    Attempt,
    AttemptRun,
    AttemptState,
    AttemptView,
    CriterionKind,
    Evaluation,
    HintReveal,
    PlayerProfile,
    Scenario,
    SubmitAccepted,
    SubmitRequest,
    derive_attempt_seed,
)
from simremap.scenarios.errors import scenario_error
from simremap.scenarios.evaluator import (
    EvaluationInput,
    EvidenceRun,
    ProbeResult,
    criterion_results,
    error_evaluation,
    evaluate,
    pending_evaluation,
)
from simremap.scenarios.events import EventLog
from simremap.scenarios.hints import HintFacts, reveal
from simremap.scenarios.ports import (
    CalibrationAudit,
    CalibrationPort,
    CalibrationRecord,
    SimulationPort,
    sleep,
)
from simremap.scenarios.probe import ProbeFailed, run_probe
from simremap.scenarios.repository import ScenarioRepository
from simremap.scenarios.trace import EvaluationTrace, traces_for_run
from simremap.scenarios.validity import RunContext, classify, expected_faults
from simremap.telemetry.datalog import LogData

__all__ = [
    "ACTIVE_STATES",
    "BASELINE_TIMEOUT_S",
    "TERMINAL_STATES",
    "AttemptService",
    "StoredRun",
    "attempt_from_row",
]

log = get_logger("simremap.scenarios")

BASELINE_TIMEOUT_S: Final = 120.0
TRACE_RETRY_DELAYS_S: Final[tuple[float, ...]] = (0.2, 0.4, 0.8)
INTERRUPTED_AFTER: Final = timedelta(minutes=5)
ACTIVE_STATES: Final = frozenset({"preparing", "in_progress", "evaluating"})
TERMINAL_STATES: Final = frozenset(
    {"passed", "failed_final", "abandoned", "expired", "failed_to_start"}
)


# --------------------------------------------------------------------------- linhas


@dataclass(frozen=True, slots=True)
class StoredRun:
    """Linha de ``attempt_run`` com o traço e o resumo usados pelo avaliador."""

    run_id: str
    pull_index: int
    run_type: str
    valid: bool
    invalid_reason: str | None
    calibration_hash: str | None
    peak_whp: float | None
    trace: EvaluationTrace
    meta: dict[str, Any]
    started_at_tick: int

    @property
    def key(self) -> str:
        return self.run_id if self.pull_index == 0 else f"{self.run_id}#{self.pull_index}"

    @staticmethod
    def from_row(row: AttemptRunRow) -> StoredRun:
        data: dict[str, Any] = dict(row.trace_json) if isinstance(row.trace_json, dict) else {}
        meta = dict(data.get("run", {}))
        return StoredRun(
            run_id=row.run_id,
            pull_index=row.pull_index,
            run_type=row.run_type,
            valid=row.valid,
            invalid_reason=row.invalid_reason,
            calibration_hash=row.calibration_hash,
            peak_whp=row.peak_whp,
            trace=EvaluationTrace(
                run_id=row.run_id, pull_index=row.pull_index, rows=list(data.get("rows", []))
            ),
            meta=meta,
            started_at_tick=int(meta.get("started_at_tick", 0)),
        )

    def evidence(self) -> EvidenceRun:
        m = self.meta
        return EvidenceRun(
            run_id=self.run_id,
            pull_index=self.pull_index,
            run_type=self.run_type,
            peak_whp=float(self.peak_whp or 0.0),
            peak_whp_rpm=float(m.get("peak_whp_rpm") or 0.0),
            peak_torque_engine_nm=float(m.get("peak_torque_engine_nm") or 0.0),
            peak_torque_rpm=float(m.get("peak_torque_rpm") or 0.0),
            failures=int(m.get("failures", 0)),
            profile_id=str(m.get("profile_id", "oem-stage")),
            trace=self.trace,
        )


def attempt_from_row(row: AttemptRow, runs: Sequence[StoredRun], scenario_sha256: str) -> Attempt:
    return Attempt(
        attempt_id=row.id,
        scenario_id=row.scenario_id,
        scenario_sha256=scenario_sha256,
        profile_id=row.profile_id,
        nickname=row.nickname,
        origin=row.origin,  # type: ignore[arg-type]
        state=AttemptState(row.state),
        session_id=row.session_id,
        calibration_id=row.calibration_id,
        seed=row.seed,
        baseline_run_id=row.baseline_run_id,
        baseline_peak_whp=row.baseline_peak_whp,
        runs=[
            AttemptRun(
                run_id=r.run_id,
                run_type=r.run_type,
                pull_index=r.pull_index,
                valid=r.valid,
                invalid_reason=r.invalid_reason,
                calibration_hash=r.calibration_hash,
                peak_whp=r.peak_whp,
            )
            for r in runs
        ],
        submissions=row.submissions,
        hints_revealed=list(row.hints_revealed_json),
        engine_restores=row.engine_restores,
        replay_status=row.replay_status,  # type: ignore[arg-type]
        started_at=row.started_at,
    )


def _sorted_runs(rows: Sequence[AttemptRunRow]) -> list[StoredRun]:
    runs = [StoredRun.from_row(r) for r in rows]
    return sorted(runs, key=lambda r: (r.started_at_tick, r.run_id, r.pull_index))


def _evaluation(row: EvaluationRow) -> Evaluation:
    return Evaluation.model_validate(row.result_json["evaluation"])


def _self_healing(scenario: Scenario) -> bool:
    """Builtin com calibração de série: o hash divergente é corrigido, não recusado (D-02)."""
    return scenario.builtin and scenario.initial_calibration.source == "vehicle_stock"


def _failures(run: DynoRun, data: LogData | None) -> int:
    logged = 0
    if data is not None:
        logged = sum(
            1
            for e in data.header.events
            if e.type == "event.failure" and not e.payload.get("simulated_only", False)
        )
    flagged = 1 if run.summary is not None and run.summary.failure_event_id else 0
    return max(logged, flagged, 1 if run.state == RunState.ENGINE_FAILED else 0)


# --------------------------------------------------------------------------- serviço


class AttemptService:
    """Tentativas locais: início, classificação, dicas, abandono e submissão."""

    def __init__(  # noqa: PLR0917 - portas injetadas
        self,
        repo: ScenarioRepository,
        catalog: ScenarioCatalog,
        sim: SimulationPort,
        calibrations: CalibrationPort,
        events: EventLog,
        audit: CalibrationAudit,
        *,
        clock: Callable[[], datetime] = utcnow,
        baseline_timeout_s: float = BASELINE_TIMEOUT_S,
    ) -> None:
        self.repo = repo
        self.catalog = catalog
        self.sim = sim
        self.calibrations = calibrations
        self.events = events
        self.audit = audit
        self.clock = clock
        self.baseline_timeout_s = baseline_timeout_s
        self._tasks: set[asyncio.Task[None]] = set()
        self._evaluating: dict[str, asyncio.Task[None]] = {}
        # Um lock por tentativa: a baseline em fundo e os GET classificam ao mesmo tempo e a
        # leitura-depois-escrita do attempt_run colidia na PK (achado do E2E T219).
        self._classify_locks: dict[str, asyncio.Lock] = {}
        # Um lock de fecho por tentativa: o abandono e a baseline em fundo podem fechar a
        # mesma tentativa ao mesmo tempo; o segundo vê o estado terminal e não o reescreve.
        self._close_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ tarefas
    def _spawn(self, coro: Any, name: str) -> asyncio.Task[None]:
        task: asyncio.Task[None] = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def drain(self) -> None:
        """Espera as tarefas em segundo plano (puxada base, avaliações)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ------------------------------------------------------------------ leitura
    async def _row(self, attempt_id: str) -> AttemptRow:
        row = await self.repo.get_attempt(attempt_id.lower())
        if row is None:
            raise scenario_error(
                "ATTEMPT_NOT_FOUND", f"A tentativa {attempt_id} não existe.", attempt_id=attempt_id
            )
        return row

    @staticmethod
    def _owned(row: AttemptRow, profile: PlayerProfile) -> None:
        if row.profile_id != profile.profile_id:
            raise scenario_error(
                "ATTEMPT_NOT_OWNED", f"A tentativa {row.id} pertence a outro perfil."
            )

    async def view(self, attempt_id: str, *, refresh: bool = True) -> AttemptView:
        row = await self._row(attempt_id)
        scenario = await self.catalog.get(row.scenario_id)
        if refresh and row.origin == "local" and row.state in ACTIVE_STATES:
            row = await self._expire_if_due(row, scenario)
            if row.state in ("in_progress", "preparing"):
                await self._classify(row, scenario, retries=False)
                row = await self._refresh_restores(row)
        return await self._view(row, scenario)

    async def _view(self, row: AttemptRow, scenario: Scenario) -> AttemptView:
        runs = _sorted_runs(await self.repo.runs_of(row.id))
        evaluations = await self.repo.evaluations_of(row.id)
        last = evaluations[-1] if evaluations else None
        progress = []
        if row.origin == "local" and row.state in ("in_progress", "preparing"):
            progress = self._progress(row, scenario, runs)
        replay = {} if last is None else dict(last.result_json.get("replay", {}))
        package = None
        if row.package_sha256:
            package = await self.repo.imported_package(row.package_sha256)
        attempt = attempt_from_row(row, runs, await self._scenario_sha(row, scenario))
        return AttemptView(
            **attempt.model_dump(),
            scenario_title=scenario.title,
            max_submissions=scenario.constraints.max_submissions,
            hints_total=len(scenario.hints),
            failure_code="BASELINE_FAILED" if row.state == "failed_to_start" else None,
            progress=progress,
            last_evaluation=None if last is None else _evaluation(last),
            evaluation_mismatch=False if last is None else last.evaluation_mismatch,
            producer_install_id=row.producer_install_id,
            package_sha256=row.package_sha256,
            imported_at=None if package is None else package.imported_at,
            replay_mismatch_run_ids=list(replay.get("mismatch_run_ids", [])),
        )

    async def _scenario_sha(self, row: AttemptRow, scenario: Scenario) -> str:
        evaluations = await self.repo.evaluations_of(row.id) if row.origin == "imported" else []
        if evaluations:
            declared = evaluations[-1].result_json.get("scenario_sha256")
            if isinstance(declared, str):
                return declared
        return str(scenario.scenario_sha256)

    async def views(self, rows: Sequence[AttemptRow]) -> list[AttemptView]:
        out = []
        cache: dict[str, Scenario] = {}
        for row in rows:
            scenario = cache.get(row.scenario_id) or await self.catalog.get(row.scenario_id)
            cache[row.scenario_id] = scenario
            out.append(await self._view(row, scenario))
        return out

    async def evaluation(self, attempt_id: str, submission: int | None) -> Evaluation:
        row = await self._row(attempt_id)
        evaluations = await self.repo.evaluations_of(row.id)
        if submission is not None:
            evaluations = [e for e in evaluations if e.submission_index == submission]
        if not evaluations:
            raise scenario_error(
                "EVALUATION_NOT_FOUND", f"A tentativa {attempt_id} não tem essa avaliação."
            )
        return _evaluation(evaluations[-1])

    # ------------------------------------------------------------------ início
    async def start(self, scenario_id: str, profile: PlayerProfile) -> AttemptView:
        scenario = await self.catalog.get(scenario_id)
        vehicle = self.catalog.vehicle(scenario.vehicle_id)
        for old in await self.repo.open_attempts(scenario.scenario_id, profile.profile_id):
            await self._close(
                old, "abandoned", event="attempt_abandoned", data={"reason": "new_attempt"}
            )
        attempt_id = str(uuid.uuid4())
        seed = scenario.seed if scenario.seed is not None else derive_attempt_seed(attempt_id)
        clone = await self._clone(scenario, vehicle, attempt_id)
        scenario = await self._check_clone_hash(scenario, clone)
        session = await self.sim.create_session(
            SessionCreateRequest(
                vehicle_id=scenario.vehicle_id,
                calibration_id=clone.calibration_id,
                profile_id=scenario.initial_profile_id,
                seed=seed,
                ambient=scenario.ambient,
                correction_standard=scenario.correction_standard,
                operator_protection=scenario.constraints.operator_protection,
                damage_enabled=True,
                fuel_id=scenario.fuel_id,
                physics_faults=expected_faults(scenario),
                attempt_id=attempt_id,
            )
        )
        now = self.clock()
        row = AttemptRow(
            id=attempt_id,
            scenario_id=scenario.scenario_id,
            profile_id=profile.profile_id,
            nickname=profile.nickname,
            origin="local",
            state="preparing",
            session_id=session.session_id,
            calibration_id=clone.calibration_id,
            seed=seed,
            submissions=0,
            hints_revealed_json=[],
            engine_restores=0,
            replay_status="not_run",
            started_at=now,
            updated_at=now,
        )
        try:
            await self.repo.add_attempt(row)
        except BaseException:
            await self.sim.delete_session(session.session_id)
            raise
        await self.events.record(
            "attempt_started",
            scenario.scenario_id,
            attempt_id,
            {"profile_id": profile.profile_id, "session_id": session.session_id, "seed": str(seed)},
        )
        log.info(
            "scenarios.attempt_started",
            attempt_id=attempt_id,
            profile_id=profile.profile_id,
            scenario_id=scenario.scenario_id,
            session_id=session.session_id,
        )
        self._spawn(
            self._baseline(attempt_id, session.session_id, scenario, vehicle),
            f"baseline-{attempt_id}",
        )
        return await self._view(row, scenario)

    async def _check_clone_hash(self, scenario: Scenario, clone: CalibrationRecord) -> Scenario:
        """Hash do clone ≠ cenário: builtin ressincroniza (D-02); os outros dão 422."""
        expected = scenario.initial_calibration.content_hash
        if clone.content_hash == expected:
            return scenario
        if not _self_healing(scenario):
            raise scenario_error(
                "SCENARIO_CALIBRATION_HASH_MISMATCH",
                "A calibração clonada tem hash diferente do initial_calibration do cenário.",
                expected_sha256=expected,
                actual_sha256=clone.content_hash,
            )
        updated = await self.catalog.resync_builtin_hash(scenario.scenario_id, clone.content_hash)
        log.warning(
            "scenarios.builtin_hash_resynced",
            scenario_id=scenario.scenario_id,
            expected_sha256=expected,
            actual_sha256=clone.content_hash,
            scenario_sha256=updated.scenario_sha256,
        )
        return updated

    async def _clone(
        self, scenario: Scenario, vehicle: VehicleInfo, attempt_id: str
    ) -> CalibrationRecord:
        name = f"tentativa {scenario.scenario_id} {attempt_id[:8]}"
        initial = scenario.initial_calibration
        try:
            if initial.source == "embedded" and initial.payload is not None:
                content = {
                    **initial.payload,
                    "vehicle_id": scenario.vehicle_id,
                    "profile_id": scenario.initial_profile_id,
                }
                return await self.calibrations.create(content, name)
            stock = await self.calibrations.stock(scenario.vehicle_id, scenario.initial_profile_id)
            if stock is None:
                raise SimRemapError(
                    f"Não há calibração de série de {scenario.vehicle_id}.",
                    code="CALIBRATION_NOT_FOUND",
                )
            return await self._clone_stock(scenario, vehicle, stock, name)
        except SimRemapError as exc:
            if exc.error_code in ("DATABASE_UNAVAILABLE",):
                raise scenario_error(
                    "CALIBRATION_SERVICE_UNAVAILABLE", "O ecu-core não respondeu ao clonar."
                ) from exc
            raise

    async def _clone_stock(
        self, scenario: Scenario, vehicle: VehicleInfo, stock: CalibrationRecord, name: str
    ) -> CalibrationRecord:
        """Clona a série; builtin com hash divergente tenta antes a fábrica do catálogo (D-02).

        Os hashes são conferidos antes de gravar, para não deixar clones órfãos.
        """
        expected = scenario.initial_calibration.content_hash
        if not _self_healing(scenario) or self._clone_hash(stock) == expected:
            return await self.calibrations.clone(stock, name)
        profile_id = scenario.initial_profile_id
        if vehicle.factory_content_hash(profile_id) == expected:
            factory = await self.calibrations.factory_clone(scenario.vehicle_id, profile_id, name)
            if factory is not None and factory.content_hash == expected:
                return factory
        return await self.calibrations.clone(stock, name)

    def _clone_hash(self, stock: CalibrationRecord) -> str | None:
        try:
            return self.calibrations.clone_hash(stock)
        except ValueError:  # série gravada num schema antigo e ilegível no atual
            return None

    async def _baseline(
        self, attempt_id: str, session_id: str, scenario: Scenario, vehicle: VehicleInfo
    ) -> None:
        request = DynoRunRequest(run_type=RunType.BASELINE_PULL, gear=scenario.constraints.gear)
        run: DynoRun | None = None
        try:
            started = await self.sim.start_run(session_id, request)
            run = await self.sim.wait_run(session_id, started.run_id, self.baseline_timeout_s)
        except (SimRemapError, TimeoutError) as exc:
            log.warning(
                "scenarios.baseline_failed", attempt_id=attempt_id, reason=type(exc).__name__
            )
        row = await self.repo.get_attempt(attempt_id)
        if row is None or row.state != "preparing":
            return
        if run is None or run.state != RunState.COMPLETED or run.summary is None:
            await self._close(row, "failed_to_start", event=None)
            return
        row = await self.repo.update_attempt(
            attempt_id,
            state="in_progress",
            baseline_run_id=run.run_id,
            baseline_peak_whp=run.summary.peak_whp,
        )
        await self.events.record(
            "baseline_completed",
            scenario.scenario_id,
            attempt_id,
            {"run_id": run.run_id, "peak_whp": run.summary.peak_whp},
        )
        await self._classify(row, scenario, retries=True)

    # ------------------------------------------------------------------ fecho
    async def _close(
        self,
        row: AttemptRow,
        state: str,
        *,
        event: str | None,
        data: dict[str, Any] | None = None,
    ) -> AttemptRow:
        """Fecha a tentativa uma só vez (idempotente): um fecho concorrente já terminal
        devolve a linha atual sem reescrever o estado nem repetir o evento."""
        lock = self._close_locks.setdefault(row.id, asyncio.Lock())
        async with lock:
            current = await self.repo.get_attempt(row.id)
            if current is not None and current.state in TERMINAL_STATES:
                return current
            updated = await self._close_unlocked(row, state, event=event, data=data)
        self._close_locks.pop(row.id, None)
        return updated

    async def _close_unlocked(
        self,
        row: AttemptRow,
        state: str,
        *,
        event: str | None,
        data: dict[str, Any] | None,
    ) -> AttemptRow:
        task = self._evaluating.pop(row.id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        if row.session_id:
            await self._record_before_close(row)
            with contextlib.suppress(SimRemapError):
                await self.sim.delete_session(row.session_id)
            self.audit.forget(row.session_id)
        updated = await self.repo.update_attempt(row.id, state=state)
        self._classify_locks.pop(row.id, None)
        if event is not None:
            await self.events.record(event, row.scenario_id, row.id, data or {})
        log.info("scenarios.attempt_closed", attempt_id=row.id, state=state)
        return updated

    async def _record_before_close(self, row: AttemptRow) -> None:
        """Classifica as puxadas terminais e conta os restauros enquanto a sessão existe.

        A carreira liquida pela tentativa fechada (``engine_broken`` vem das falhas gravadas
        e de ``engine_restores``): sem isto, quebrar o motor e abandonar (ou restaurar e
        logo submeter) sem um ``GET`` da tentativa escapava do custo do motor.
        """
        if row.origin != "local":
            return
        with contextlib.suppress(SimRemapError):
            await self._classify(row, await self.catalog.get(row.scenario_id), retries=False)
            await self._refresh_restores(row)

    async def _expire_if_due(self, row: AttemptRow, scenario: Scenario) -> AttemptRow:
        limit = scenario.constraints.time_limit_min
        if limit is None or row.state != "in_progress":
            return row
        if self.clock() - row.started_at < timedelta(minutes=limit):
            return row
        return await self._close(row, "expired", event=None)

    async def abandon(self, attempt_id: str, profile: PlayerProfile) -> AttemptView:
        row = await self._row(attempt_id)
        self._owned(row, profile)
        if row.state not in ("preparing", "in_progress"):
            raise scenario_error(
                "ATTEMPT_NOT_IN_PROGRESS", f"A tentativa está em {row.state}.", state=row.state
            )
        row = await self._close(
            row, "abandoned", event="attempt_abandoned", data={"reason": "user"}
        )
        return await self._view(row, await self.catalog.get(row.scenario_id))

    async def _refresh_restores(self, row: AttemptRow) -> AttemptRow:
        if not row.session_id:
            return row
        count = await self.sim.restore_count(row.session_id)
        if count is None or count == row.engine_restores:
            return row
        return await self.repo.update_attempt(row.id, engine_restores=count)

    # ------------------------------------------------------------------ classificação
    async def _log(self, run_id: str, *, retries: bool) -> LogData | None:
        delays = TRACE_RETRY_DELAYS_S if retries else ()
        for delay in (*delays, None):
            try:
                return await self.sim.load_log(run_id)
            except SimRemapError:
                if delay is None:
                    return None
                await sleep(delay)
        return None  # pragma: no cover

    async def _classify(
        self, row: AttemptRow, scenario: Scenario, *, retries: bool
    ) -> list[StoredRun]:
        """Classifica as puxadas terminais novas da sessão e devolve todas as gravadas."""
        lock = self._classify_locks.setdefault(row.id, asyncio.Lock())
        async with lock:
            return await self._classify_unlocked(row, scenario, retries=retries)

    async def _classify_unlocked(
        self, row: AttemptRow, scenario: Scenario, *, retries: bool
    ) -> list[StoredRun]:
        if not row.session_id:
            return _sorted_runs(await self.repo.runs_of(row.id))
        stored = {(r.run_id, r.pull_index): r for r in await self.repo.runs_of(row.id)}
        session = await self.sim.session(row.session_id)
        if session is None:
            return _sorted_runs(list(stored.values()))
        vehicle = self.catalog.vehicle(scenario.vehicle_id)
        new_rows: list[AttemptRunRow] = []
        for run in await self.sim.runs_of(row.session_id):
            if run.request.probe is not None or run.state not in TERMINAL_RUN_STATES:
                continue
            keys = [k for k in stored if k[0] == run.run_id]
            if keys and all(stored[k].invalid_reason != "trace_unavailable" for k in keys):
                continue
            new_rows.extend(await self._classify_run(row, scenario, vehicle, session, run, retries))
        if new_rows:
            await self.repo.upsert_runs(new_rows)
            for r in new_rows:
                if (r.run_id, r.pull_index) not in stored:
                    await self.events.record(
                        "run_classified",
                        scenario.scenario_id,
                        row.id,
                        {
                            "run_id": r.run_id,
                            "pull_index": r.pull_index,
                            "valid": r.valid,
                            "invalid_reason": r.invalid_reason,
                        },
                    )
            for r in new_rows:
                stored[(r.run_id, r.pull_index)] = r
        return _sorted_runs(list(stored.values()))

    async def _classify_run(  # noqa: PLR0917
        self,
        row: AttemptRow,
        scenario: Scenario,
        vehicle: VehicleInfo,
        session: Any,
        run: DynoRun,
        retries: bool,
    ) -> list[AttemptRunRow]:
        data = await self._log(run.run_id, retries=retries)
        multi = run.run_type == RunType.MULTI_PULL and bool(run.pulls)
        traces: dict[int, EvaluationTrace] = {}
        if data is not None:
            traces = traces_for_run(
                data, run_id=run.run_id, pedal_pct=run.request.pedal_pct, multi=multi
            )
        t0 = run.started_at_tick / run.sim_hz
        t1 = None if run.ended_at_tick is None else run.ended_at_tick / run.sim_hz
        ctx = RunContext(
            session=session,
            seed=row.seed,
            rev_limit_rpm=vehicle.rev_limit_rpm,
            profile_id=str(data.header.profile_id) if data is not None else str(session.profile_id),
            calibration_hashes=frozenset(self.audit.hashes_between(row.session_id or "", t0, t1)),
            trace_available=data is not None,
        )
        failures = _failures(run, data)
        rows: list[AttemptRunRow] = []
        pulls = {p.pull_index: p for p in run.pulls}
        for verdict in classify(run, scenario, ctx):
            summary = (
                pulls[verdict.pull_index].summary if verdict.pull_index in pulls else run.summary
            )
            trace = traces.get(verdict.pull_index) or traces.get(0)
            meta = {
                "state": run.state.value,
                "abort_reason": None if run.abort_reason is None else run.abort_reason.value,
                "started_at_tick": run.started_at_tick,
                "profile_id": ctx.profile_id,
                "failures": failures,
                "knock_events": 0 if summary is None else summary.knock_events,
                "peak_whp_rpm": None if summary is None else summary.peak_whp_rpm,
                "peak_torque_engine_nm": None if summary is None else summary.peak_torque_engine_nm,
                "peak_torque_rpm": None if summary is None else summary.peak_torque_rpm,
                "calibration_id": run.calibration_id,
                "curve_sha256": run.curve_sha256,
            }
            rows.append(
                AttemptRunRow(
                    attempt_id=row.id,
                    run_id=run.run_id,
                    pull_index=verdict.pull_index,
                    run_type=verdict.run_type,
                    valid=verdict.valid,
                    invalid_reason=verdict.invalid_reason,
                    calibration_hash=verdict.calibration_hash,
                    peak_whp=verdict.peak_whp,
                    trace_json={
                        "columns": list(trace.columns) if trace else [],
                        "rows": [] if trace is None else trace.rows,
                        "run": meta,
                    },
                )
            )
        return rows

    # ------------------------------------------------------------------ evidências
    @staticmethod
    def _select(
        scenario: Scenario,
        runs: Sequence[StoredRun],
        submitted_hash: str | None,
        run_ids: Sequence[str] | None,
    ) -> tuple[list[StoredRun], list[str]]:
        """Puxadas de evidência e ``ignored_runs`` (``<run>[#pull]:<motivo>``)."""

        def reason(r: StoredRun) -> str | None:
            if not r.valid:
                return r.invalid_reason or "invalid"
            if submitted_hash is not None and r.calibration_hash != submitted_hash:
                return "calibration_not_submitted"
            return None

        ignored: list[str] = []
        if run_ids:
            wanted = list(dict.fromkeys(run_ids))
            chosen: list[StoredRun] = []
            for rid in wanted:
                matches = [r for r in runs if r.run_id == rid]
                if not matches:
                    ignored.append(f"{rid}:run_not_in_attempt")
                for r in matches:
                    why = reason(r)
                    if why is None:
                        chosen.append(r)
                    else:
                        ignored.append(f"{r.key}:{why}")
            return chosen, ignored
        valid = [r for r in runs if reason(r) is None]
        need = scenario.criteria.required_valid_pulls
        chosen = valid[-need:] if need > 0 else []
        ignored = [f"{r.key}:{reason(r)}" for r in runs if reason(r) is not None]
        return chosen, ignored

    def _facts(
        self,
        row: AttemptRow,
        runs: Sequence[StoredRun],
        evaluations: Sequence[EvaluationRow],
        sim_time_s: float,
    ) -> HintFacts:
        events: set[str] = set()
        for r in runs:
            if not r.valid:
                events.add("invalid_run")
            if r.invalid_reason == "engine_failed" or r.meta.get("state") == "engine_failed":
                events.add("engine_failed")
            if r.meta.get("abort_reason") == AbortReason.EGT_LIMIT.value:
                events.add("egt_limit")
            if any((v or 0) > 0 for v in r.trace.column("knock_retard_max_deg")):
                events.add("knock_retard")
        failed = 0
        for e in evaluations:
            if e.status != "completed" or e.passed:
                continue
            failed += 1
            result = _evaluation(e)
            if any(
                not c.passed
                and c.kind in (CriterionKind.MAX_EGT_C, CriterionKind.MAX_EGT_OVERRUN_C)
                for c in result.results
            ):
                events.add("egt_limit")
        return HintFacts(failed_submissions=failed, sim_time_s=sim_time_s, events=frozenset(events))

    def _progress(
        self, row: AttemptRow, scenario: Scenario, runs: Sequence[StoredRun]
    ) -> list[Any]:
        current = None if not row.session_id else self.sim.current_calibration_hash(row.session_id)
        chosen, ignored = self._select(scenario, runs, current, None)
        inp = EvaluationInput(
            attempt_id=row.id,
            submission_index=max(1, row.submissions + 1),
            baseline_peak_whp=row.baseline_peak_whp,
            evidence=[r.evidence() for r in chosen],
            ignored_runs=ignored,
            hints_revealed=list(row.hints_revealed_json),
        )
        return criterion_results(scenario, inp)

    # ------------------------------------------------------------------ dicas
    async def reveal_hint(self, attempt_id: str, profile: PlayerProfile) -> HintReveal:
        row = await self._row(attempt_id)
        self._owned(row, profile)
        scenario = await self.catalog.get(row.scenario_id)
        runs = (
            await self._classify(row, scenario, retries=False)
            if row.state in ACTIVE_STATES
            else _sorted_runs(await self.repo.runs_of(row.id))
        )
        session = None if not row.session_id else await self.sim.session(row.session_id)
        facts = self._facts(
            row,
            runs,
            await self.repo.evaluations_of(row.id),
            0.0 if session is None else session.t_sim_s,
        )
        result = reveal(scenario, list(row.hints_revealed_json), facts)
        await self.repo.update_attempt(
            row.id, hints_revealed_json=[*row.hints_revealed_json, result.order]
        )
        await self.events.record("hint_revealed", row.scenario_id, row.id, {"order": result.order})
        return result

    # ------------------------------------------------------------------ submissão
    async def _attempt_calibrations(self, row: AttemptRow, runs: Sequence[StoredRun]) -> set[str]:
        ids = {row.calibration_id}
        ids |= {str(r.meta["calibration_id"]) for r in runs if r.meta.get("calibration_id")}
        if row.session_id:
            ids |= self.audit.calibration_ids(row.session_id)
            session = await self.sim.session(row.session_id)
            if session is not None:
                ids.add(session.calibration_id)
        return ids

    async def submit(
        self, attempt_id: str, profile: PlayerProfile, body: SubmitRequest
    ) -> SubmitAccepted:
        row = await self._row(attempt_id)
        self._owned(row, profile)
        scenario = await self.catalog.get(row.scenario_id)
        row = await self._expire_if_due(row, scenario)
        if row.state != "in_progress":
            raise scenario_error(
                "ATTEMPT_NOT_IN_PROGRESS", f"A tentativa está em {row.state}.", state=row.state
            )
        limit = scenario.constraints.max_submissions
        if row.submissions >= limit:
            raise scenario_error(
                "SUBMISSION_LIMIT_REACHED", f"Já foram feitas as {limit} submissões permitidas."
            )
        session = None if not row.session_id else await self.sim.session(row.session_id)
        if session is not None and session.active_run_id is not None:
            raise SimRemapError(
                f"A puxada {session.active_run_id} está em andamento.", code="RUN_IN_PROGRESS"
            )
        runs = await self._classify(row, scenario, retries=True)
        if body.calibration_id not in await self._attempt_calibrations(row, runs):
            raise scenario_error(
                "CALIBRATION_NOT_IN_ATTEMPT",
                f"A calibração {body.calibration_id} não pertence à tentativa.",
            )
        frozen = await self.calibrations.get(body.calibration_id)
        index = row.submissions + 1
        evaluation_id = str(uuid.uuid4())
        now = self.clock()
        pending = pending_evaluation(row.id, index, evaluation_id=evaluation_id, created_at=now)
        await self.repo.add_evaluation(
            EvaluationRow(
                id=evaluation_id,
                attempt_id=row.id,
                submission_index=index,
                status="pending",
                result_json={"evaluation": pending.model_dump(mode="json")},
                created_at=now,
            )
        )
        await self.repo.update_attempt(row.id, submissions=index, state="evaluating")
        await self.events.record(
            "attempt_submitted",
            row.scenario_id,
            row.id,
            {"submission_index": index, "calibration_content_hash": frozen.content_hash},
        )
        task = self._spawn(
            self._evaluate(row.id, evaluation_id, index, body, frozen),
            f"evaluate-{row.id}-{index}",
        )
        self._evaluating[row.id] = task
        return SubmitAccepted(attempt_id=row.id, submission_index=index)

    async def _initial_content(self, scenario: Scenario) -> dict[str, Any] | None:
        initial = scenario.initial_calibration
        if initial.source == "embedded":
            return initial.payload
        stock = await self.calibrations.stock(scenario.vehicle_id, scenario.initial_profile_id)
        return None if stock is None else stock.content

    async def _evaluate(
        self,
        attempt_id: str,
        evaluation_id: str,
        index: int,
        body: SubmitRequest,
        frozen: CalibrationRecord,
    ) -> None:
        row = await self._row(attempt_id)
        scenario = await self.catalog.get(row.scenario_id)
        created = self.clock()
        code: str | None = None
        probe: ProbeResult | None = None
        inp: EvaluationInput | None = None
        try:
            runs = await self._classify(row, scenario, retries=True)
            chosen, ignored = self._select(scenario, runs, frozen.content_hash, body.run_ids)
            if any(
                r.invalid_reason == "trace_unavailable"
                for r in runs
                if r.calibration_hash == frozen.content_hash
            ):
                code = "TRACE_UNAVAILABLE"
            else:
                probe = await self._probe(row, scenario, chosen)
                initial = await self._initial_content(scenario)
                locked = _changed_tables(
                    initial, frozen.content, scenario.constraints.locked_table_ids
                )
                inp = EvaluationInput(
                    attempt_id=row.id,
                    submission_index=index,
                    baseline_peak_whp=row.baseline_peak_whp,
                    evidence=[r.evidence() for r in chosen],
                    ignored_runs=ignored,
                    calibration_content_hash=frozen.content_hash,
                    locked_tables_changed=locked,
                    declared_defect=body.declared_defect,
                    probe=probe,
                    hints_revealed=list(row.hints_revealed_json),
                )
        except ProbeFailed:
            code = "PROBE_FAILED"
        if code is not None or inp is None:
            await self._fail_evaluation(row, evaluation_id, index, code or "PROBE_FAILED", created)
            return
        evaluation = evaluate(scenario, inp, evaluation_id=evaluation_id, created_at=created)
        # O estado da tentativa (e o fecho da sessão) vem antes da avaliação ``completed``: quem
        # espera a avaliação e logo inicia outra tentativa, liquida a carreira ou volta a
        # submeter não pode ver ``evaluating`` nem a sessão ainda aberta.
        await self._settle_attempt(row, scenario, index, passed=bool(evaluation.passed))
        await self.repo.update_evaluation(
            evaluation_id,
            status="completed",
            passed=evaluation.passed,
            total_score=evaluation.total_score,
            evaluation_sha256=evaluation.evaluation_sha256,
            result_json={
                "evaluation": evaluation.model_dump(mode="json"),
                "input": inp.model_dump(mode="json"),
                "calibration": {
                    "calibration_id": frozen.calibration_id,
                    "version": frozen.version,
                    "content_hash": frozen.content_hash,
                },
                "scenario_sha256": scenario.scenario_sha256,
            },
        )
        self._evaluating.pop(row.id, None)

    async def _settle_attempt(
        self, row: AttemptRow, scenario: Scenario, index: int, *, passed: bool
    ) -> None:
        """Estado da tentativa depois da avaliação: ``passed``, ``failed_final`` ou de novo
        ``in_progress``; os terminais fecham a sessão do dinamômetro."""
        if passed:
            await self.events.record(
                "attempt_passed", row.scenario_id, row.id, {"submission_index": index}
            )
            await self._close(await self._row(row.id), "passed", event=None)
            return
        final = index >= scenario.constraints.max_submissions
        await self.events.record(
            "attempt_failed", row.scenario_id, row.id, {"submission_index": index, "final": final}
        )
        if final:
            await self._close(await self._row(row.id), "failed_final", event=None)
        else:
            await self.repo.update_attempt(row.id, state="in_progress")

    async def _probe(
        self, row: AttemptRow, scenario: Scenario, chosen: Sequence[StoredRun]
    ) -> ProbeResult | None:
        margin = next(
            (c for c in scenario.criteria.criteria if c.kind == CriterionKind.MIN_KNOCK_MARGIN_DEG),
            None,
        )
        if margin is None or not chosen:
            return None
        if not row.session_id:
            raise ProbeFailed("tentativa sem sessão")
        source = await self.sim.get_run(chosen[0].run_id)
        if source is None:
            raise ProbeFailed("puxada de evidência inexistente")
        vehicle = self.catalog.vehicle(scenario.vehicle_id)
        return await run_probe(
            self.sim,
            row.session_id,
            source,
            float(margin.threshold or 0.0),
            rev_limit_rpm=vehicle.rev_limit_rpm,
        )

    async def _fail_evaluation(
        self, row: AttemptRow, evaluation_id: str, index: int, code: str, created: datetime
    ) -> None:
        error = error_evaluation(
            row.id,
            index,
            code,
            evaluation_id=evaluation_id,
            created_at=created,
            hints_revealed=list(row.hints_revealed_json),
        )
        await self.repo.update_evaluation(
            evaluation_id, status="error", result_json={"evaluation": error.model_dump(mode="json")}
        )
        current = await self._row(row.id)
        await self.repo.update_attempt(
            row.id, state="in_progress", submissions=max(0, current.submissions - 1)
        )
        self._evaluating.pop(row.id, None)
        log.warning("scenarios.evaluation_error", attempt_id=row.id, code=code)

    # ------------------------------------------------------------------ arranque
    async def recover(self) -> dict[str, int]:
        """EC-15: avaliações ``pending`` > 5 min ⇒ ``error`` (``EVALUATION_INTERRUPTED``);
        tentativas ``preparing`` sem a tarefa da puxada base ⇒ ``failed_to_start``."""
        now = self.clock()
        interrupted = 0
        for ev in await self.repo.pending_evaluations(now - INTERRUPTED_AFTER):
            row = await self.repo.get_attempt(ev.attempt_id)
            if row is None:
                continue
            await self._fail_evaluation(
                row, ev.id, ev.submission_index, "EVALUATION_INTERRUPTED", ev.created_at
            )
            interrupted += 1
        stale = 0
        for row in await self.repo.attempts_in_states(("preparing",)):
            if row.origin == "local":
                await self.repo.update_attempt(row.id, state="failed_to_start")
                stale += 1
        return {"evaluations_interrupted": interrupted, "preparing_failed": stale}


def _changed_tables(
    initial: dict[str, Any] | None, frozen: dict[str, Any], locked: Sequence[str]
) -> list[str]:
    """Tabelas bloqueadas cujo conteúdo mudou entre a calibração inicial e a congelada."""
    if not locked:
        return []
    before = {} if initial is None else dict(initial.get("tables", {}))
    after = dict(frozen.get("tables", {}))
    return sorted(t for t in locked if before.get(t) != after.get(t))
