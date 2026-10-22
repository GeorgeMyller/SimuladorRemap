"""Serviço do dano fora do laço: laudo, persistência de saúde e falhas (RF-20, RF-22, RF-27, RF-30).

- O laudo é gerado numa thread (``asyncio.to_thread``), nunca no tick. Enquanto corre,
  ``get_report`` devolve 409 ``FORENSIC_REPORT_PENDING`` com ``Retry-After: 1``. Acima de
  5 s regista ``forensic.timeout`` e grava o laudo mínimo (EC-07).
- Gravação com 3 novas tentativas (100, 200, 400 ms); se o banco continuar indisponível,
  o laudo fica em memória (máximo 20 por sessão) e o GET responde
  ``X-Simremap-Persisted: false`` (EC-08).
- ``engine_health`` é escrita no fim de puxada, em falhas e em restaurações (nunca por tick).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from simremap.core.logging import get_logger
from simremap.damage.contracts import (
    CalibrationDiff,
    ComponentHealth,
    EngineHealth,
    FailureEvent,
    ForensicReport,
    ReportKind,
)
from simremap.damage.errors import DamageError
from simremap.damage.forensic import build_forensic_report, build_minimal_report
from simremap.damage.session_port import SessionView
from simremap.damage.trace import DamageTraceSnapshot
from simremap.db.models.damage import EngineHealthRow, FailureEventRow, ForensicReportRow
from simremap.dyno.contracts import DynoRun

__all__ = ["ForensicService", "forensic_report_url"]

log = get_logger("simremap.damage")

GENERATION_TIMEOUT_S: Final = 5.0
RETRY_DELAYS_S: Final = (0.1, 0.2, 0.4)
MAX_REPORTS_PER_SESSION: Final = 20


def forensic_report_url(run_id: str) -> str:
    return f"/api/v1/runs/{run_id}/forensic-report"


class ForensicService:
    """Gera, guarda e serve laudos; persiste ``engine_health`` e ``failure_event``."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        timeout_s: float = GENERATION_TIMEOUT_S,
        retry_delays_s: Sequence[float] = RETRY_DELAYS_S,
        max_per_session: int = MAX_REPORTS_PER_SESSION,
        builder: Callable[..., ForensicReport] = build_forensic_report,
    ) -> None:
        self._maker = sessionmaker
        self._timeout_s = timeout_s
        self._retry = tuple(retry_delays_s)
        self._max_per_session = max_per_session
        self._builder = builder
        self._pending: dict[str, asyncio.Task[ForensicReport]] = {}
        self._reports: OrderedDict[str, tuple[ForensicReport, bool]] = OrderedDict()
        self._by_session: dict[str, deque[str]] = {}

    # ------------------------------------------------------------------ laudo

    def submit(
        self,
        trace: DamageTraceSnapshot,
        run: DynoRun,
        baseline: DynoRun | None = None,
        calibration_diff: CalibrationDiff | None = None,
        kind: ReportKind = "failure",
    ) -> asyncio.Task[ForensicReport]:
        """Agenda a geração do laudo (chamado no tick seguinte à falha, fora do laço)."""
        task = asyncio.create_task(self.generate(trace, run, baseline, calibration_diff, kind))
        self._pending[run.run_id] = task
        run_id = run.run_id

        def _done(_task: asyncio.Task[ForensicReport]) -> None:
            if self._pending.get(run_id) is _task:
                del self._pending[run_id]

        task.add_done_callback(_done)
        return task

    async def generate(
        self,
        trace: DamageTraceSnapshot,
        run: DynoRun,
        baseline: DynoRun | None = None,
        calibration_diff: CalibrationDiff | None = None,
        kind: ReportKind = "failure",
    ) -> ForensicReport:
        """Gera o laudo numa thread com corte em 5 s e persiste-o."""
        created_at = datetime.now(UTC)
        try:
            report = await asyncio.wait_for(
                asyncio.to_thread(
                    self._builder,
                    trace,
                    run,
                    baseline,
                    calibration_diff,
                    kind,
                    created_at=created_at,
                ),
                timeout=self._timeout_s,
            )
        except TimeoutError:
            log.warning("forensic.timeout", run_id=run.run_id, timeout_s=self._timeout_s)
            report = build_minimal_report(trace, run, kind, created_at=created_at)
        persisted = await self._persist_report(report)
        self._store(report, persisted)
        return report

    def _store(self, report: ForensicReport, persisted: bool) -> None:
        self._reports[report.run_id] = (report, persisted)
        runs = self._by_session.setdefault(report.session_id, deque())
        if report.run_id in runs:
            runs.remove(report.run_id)
        runs.append(report.run_id)
        while len(runs) > self._max_per_session:
            self._reports.pop(runs.popleft(), None)

    def is_pending(self, run_id: str) -> bool:
        task = self._pending.get(run_id)
        return task is not None and not task.done()

    async def get_report(self, run_id: str) -> tuple[ForensicReport, bool]:
        """``(laudo, persistido)``; 409 em geração, 404 sem laudo."""
        if self.is_pending(run_id):
            raise DamageError(
                "O laudo forense ainda está em geração.",
                code="FORENSIC_REPORT_PENDING",
                headers={"Retry-After": "1"},
            )
        cached = self._reports.get(run_id)
        if cached is not None:
            return cached
        if self._maker is not None:
            try:
                async with self._maker() as session:
                    row = await _report_by_run(session, run_id)
            except SQLAlchemyError:
                row = None
            if row is not None:
                return ForensicReport.model_validate(row.report_json), True
        raise DamageError(
            "A puxada não tem falha nem quase-falha com laudo.", code="FORENSIC_REPORT_NOT_FOUND"
        )

    async def _persist_report(self, report: ForensicReport) -> bool:
        if self._maker is None:
            return False

        async def write(session: AsyncSession) -> None:
            if report.failure_event is not None:
                await session.merge(_failure_row(report.failure_event))
            existing = await _report_by_run(session, report.run_id)
            if existing is not None:
                await session.delete(existing)
                await session.flush()
            session.add(
                ForensicReportRow(
                    report_id=report.report_id,
                    run_id=report.run_id,
                    session_id=report.session_id,
                    failure_event_id=(
                        None
                        if report.failure_event is None
                        else report.failure_event.failure_event_id
                    ),
                    report_kind=report.report_kind,
                    report_json=report.model_dump(mode="json"),
                    report_sha256=report.report_sha256,
                    generator_version=report.generator_version,
                    created_at=report.created_at,
                )
            )

        return await self._with_retry(write, "forensic_report", run_id=report.run_id)

    # ------------------------------------------------------------------ saúde e falhas

    async def persist_failures(self, events: Iterable[FailureEvent]) -> bool:
        """Insere os ``FailureEvent`` (idempotente por ``failure_event_id``)."""
        rows = [_failure_row(e) for e in events]
        for event in rows:
            log.info(
                "damage.failure",
                session_id=event.session_id,
                run_id=event.run_id,
                mode=event.mode,
                mechanism=event.mechanism,
                component_id=event.component_id,
                tick=event.tick,
            )
        if not rows or self._maker is None:
            return False

        async def write(session: AsyncSession) -> None:
            for row in rows:
                await session.merge(row)

        return await self._with_retry(write, "failure_event")

    async def persist_engine_health(
        self, health: EngineHealth, rod_weights: Sequence[float], tick: int
    ) -> bool:
        """Grava a projeção ``engine_health`` (1 linha por sessão)."""
        if self._maker is None:
            return False

        async def write(session: AsyncSession) -> None:
            row = await session.get(EngineHealthRow, health.session_id)
            components = [c.model_dump(mode="json") for c in health.components]
            if row is None:
                session.add(
                    EngineHealthRow(
                        session_id=health.session_id,
                        components_json=components,
                        engine_locked=health.engine_locked,
                        restore_count=health.restore_count,
                        rod_weights_json=list(rod_weights),
                        updated_at_tick=tick,
                    )
                )
            else:
                row.components_json = components
                row.engine_locked = health.engine_locked
                row.restore_count = health.restore_count
                if rod_weights:
                    row.rod_weights_json = list(rod_weights)
                row.updated_at_tick = tick
                session.add(row)

        return await self._with_retry(write, "engine_health", session_id=health.session_id)

    async def load_engine_health(
        self, view: SessionView, include_failures: bool = True
    ) -> EngineHealth | None:
        """Último ``engine_health`` persistido (worker indisponível, EC-13)."""
        if self._maker is None:
            return None
        try:
            async with self._maker() as session:
                row = await session.get(EngineHealthRow, view.session_id)
                if row is None:
                    return None
                failures: list[FailureEvent] = []
                if include_failures:
                    result = await session.execute(
                        select(FailureEventRow)
                        .where(col(FailureEventRow.session_id) == view.session_id)
                        .order_by(
                            col(FailureEventRow.t_sim_s), col(FailureEventRow.failure_event_id)
                        )
                    )
                    failures = [_failure_from_row(r) for r in result.scalars()]
        except SQLAlchemyError:
            return None
        return EngineHealth.build(
            session_id=view.session_id,
            vehicle_id=view.vehicle_id,
            t_sim_s=view.t_sim_s,
            damage_enabled=view.damage_enabled,
            engine_locked=row.engine_locked,
            components=[ComponentHealth.model_validate(c) for c in row.components_json],
            failures=failures,
            restore_count=row.restore_count,
            last_forensic_report_url=view.last_forensic_report_url,
        )

    # ------------------------------------------------------------------ utilitários

    async def _with_retry(
        self, write: Callable[[AsyncSession], Awaitable[None]], table: str, **context: object
    ) -> bool:
        if self._maker is None:
            return False
        delays = (*self._retry, None)
        for delay in delays:
            try:
                async with self._maker() as session:
                    await write(session)
                    await session.commit()
                return True
            except SQLAlchemyError as exc:
                log.warning(
                    "damage.persist_failed", table=table, error=type(exc).__name__, **context
                )
                if delay is None:
                    return False
                await asyncio.sleep(delay)
        return False  # pragma: no cover - o laço sempre retorna


async def _report_by_run(session: AsyncSession, run_id: str) -> ForensicReportRow | None:
    result = await session.execute(
        select(ForensicReportRow).where(col(ForensicReportRow.run_id) == run_id)
    )
    return result.scalars().first()


def _failure_row(event: FailureEvent) -> FailureEventRow:
    return FailureEventRow(
        failure_event_id=event.failure_event_id,
        session_id=event.session_id,
        run_id=event.run_id,
        tick=event.tick,
        t_sim_s=event.t_sim_s,
        cylinder=event.cylinder,
        component_id=event.component_id,
        mode=event.mode.value,
        mechanism=event.mechanism.value,
        catastrophic=event.catastrophic,
        simulated_only=event.simulated_only,
        health_after=event.health_after,
        causal_json=dict(event.causal_variables),
    )


def _failure_from_row(row: FailureEventRow) -> FailureEvent:
    return FailureEvent(
        failure_event_id=row.failure_event_id,
        session_id=row.session_id,
        run_id=row.run_id,
        tick=row.tick,
        t_sim_s=row.t_sim_s,
        cylinder=row.cylinder,
        component_id=row.component_id,
        mode=row.mode,  # type: ignore[arg-type]
        mechanism=row.mechanism,  # type: ignore[arg-type]
        catastrophic=row.catastrophic,
        simulated_only=row.simulated_only,
        health_after=row.health_after,
        causal_variables={k: float(v) for k, v in row.causal_json.items()},
    )
