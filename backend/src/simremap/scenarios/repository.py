"""Persistência dos cenários sobre as 7 tabelas da migração ``0007_scenarios_base``
(data-model 2.7, 7.3; training-scenarios seção 9).

- ``player_profile``: unicidade sem caixa pelo índice ``uq_player_profile_nickname_lower``
  (``IntegrityError`` ⇒ 409 ``NICKNAME_TAKEN``).
- ``scenario``: ``content_json`` guarda o ``Scenario`` completo; cenários embutidos por
  ``upsert_builtin`` (idempotente).
- ``attempt``, ``attempt_run`` (``trace_json`` = linhas do ``EvaluationTrace``),
  ``evaluation`` (``result_json`` = avaliação + entrada congelada), ``imported_package``.
- ``scenario_event``: eventos locais; ``data_json`` nunca leva ``nickname`` (zero PII,
  verificado em ``add_event``).

Falhas do banco: ``DATABASE_UNAVAILABLE`` (503, ``Retry-After: 2``); disco cheio
(``database or disk is full``/``No space left``) ⇒ 507 ``STORAGE_FULL`` com a transação
revertida (EC-16).
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col

from simremap.core.errors import SimRemapError
from simremap.db.base import utcnow
from simremap.db.models.scenarios import (
    AttemptRow,
    AttemptRunRow,
    EvaluationRow,
    ImportedPackageRow,
    PlayerProfileRow,
    ScenarioEventRow,
    ScenarioRow,
)
from simremap.scenarios.contracts import PlayerProfile, Role, Scenario
from simremap.scenarios.errors import scenario_error

__all__ = ["PII_KEYS", "AttemptCursor", "ImportBundle", "ScenarioRepository"]

T = TypeVar("T")

PII_KEYS = frozenset({"nickname", "author_nickname", "email", "ip", "name"})
"""Chaves proibidas em ``scenario_event.data_json`` (data-model 7.3)."""

_FULL_MARKERS = ("database or disk is full", "no space left", "disk full")


def _storage_full(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _FULL_MARKERS)


def _contains_pii(value: Any) -> bool:
    if isinstance(value, dict):
        return any(k in PII_KEYS or _contains_pii(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_pii(v) for v in value)
    return False


class AttemptCursor:
    """Cursor opaco de ``GET /api/v1/attempts``: ``(started_at, attempt_id)`` em base64."""

    @staticmethod
    def encode(started_at: datetime, attempt_id: str) -> str:
        raw = json.dumps([started_at.isoformat(), attempt_id]).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def decode(cursor: str) -> tuple[datetime, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            started, attempt_id = json.loads(raw)
            return datetime.fromisoformat(str(started)), str(attempt_id)
        except (ValueError, TypeError) as exc:
            raise SimRemapError("Cursor inválido.", code="VALIDATION_FAILED") from exc


class ImportBundle:
    """Linhas gravadas numa única transação pela importação de um pacote (RF-19 a RF-21)."""

    def __init__(
        self,
        package: ImportedPackageRow,
        scenario: ScenarioRow | None = None,
        attempt: AttemptRow | None = None,
        runs: Sequence[AttemptRunRow] = (),
        evaluation: EvaluationRow | None = None,
        replace_attempt: bool = False,
    ) -> None:
        self.package = package
        self.scenario = scenario
        self.attempt = attempt
        self.runs = list(runs)
        self.evaluation = evaluation
        self.replace_attempt = replace_attempt


class ScenarioRepository:
    """Acesso às 7 tabelas dos cenários (uma transação por operação)."""

    def __init__(self, maker: async_sessionmaker[AsyncSession] | None) -> None:
        self._maker = maker

    @property
    def available(self) -> bool:
        return self._maker is not None

    async def _run(self, op: Callable[[AsyncSession], Awaitable[T]], *, write: bool = False) -> T:
        if self._maker is None:
            raise SimRemapError(
                "Banco de dados indisponível.",
                code="DATABASE_UNAVAILABLE",
                headers={"Retry-After": "2"},
            )
        try:
            async with self._maker() as db:
                result = await op(db)
                if write:
                    await db.commit()
                return result
        except IntegrityError:
            raise
        except SimRemapError:
            raise
        except (OperationalError, SQLAlchemyError) as exc:
            if _storage_full(exc):
                raise SimRemapError(
                    "Armazenamento cheio; a operação foi revertida.", code="STORAGE_FULL"
                ) from exc
            raise SimRemapError(
                "Banco de dados indisponível.",
                code="DATABASE_UNAVAILABLE",
                headers={"Retry-After": "2"},
            ) from exc

    # ------------------------------------------------------------------ perfis
    async def list_profiles(self) -> list[PlayerProfile]:
        async def op(db: AsyncSession) -> list[PlayerProfile]:
            rows = (
                await db.execute(
                    select(PlayerProfileRow).order_by(
                        col(PlayerProfileRow.created_at), col(PlayerProfileRow.id)
                    )
                )
            ).scalars()
            return [_profile(r) for r in rows]

        return await self._run(op)

    async def count_profiles(self) -> int:
        async def op(db: AsyncSession) -> int:
            return int(
                (await db.execute(select(func.count()).select_from(PlayerProfileRow))).scalar_one()
            )

        return await self._run(op)

    async def get_profile(self, profile_id: str) -> PlayerProfile | None:
        async def op(db: AsyncSession) -> PlayerProfile | None:
            row = await db.get(PlayerProfileRow, profile_id)
            return None if row is None else _profile(row)

        return await self._run(op)

    async def add_profile(self, profile: PlayerProfile) -> PlayerProfile:
        async def op(db: AsyncSession) -> PlayerProfile:
            db.add(
                PlayerProfileRow(
                    id=profile.profile_id,
                    nickname=profile.nickname,
                    role=profile.role.value,
                    created_at=profile.created_at,
                )
            )
            await db.flush()
            return profile

        try:
            return await self._run(op, write=True)
        except IntegrityError as exc:
            raise scenario_error(
                "NICKNAME_TAKEN",
                f"O nickname {profile.nickname!r} já está em uso nesta estação.",
            ) from exc

    # ------------------------------------------------------------------ cenários
    async def get_scenario(self, scenario_id: str) -> Scenario | None:
        async def op(db: AsyncSession) -> Scenario | None:
            row = await db.get(ScenarioRow, scenario_id)
            return None if row is None else _scenario(row)

        return await self._run(op)

    async def list_scenarios(self, kind: str | None = None) -> list[Scenario]:
        async def op(db: AsyncSession) -> list[Scenario]:
            stmt = select(ScenarioRow).order_by(col(ScenarioRow.builtin).desc(), ScenarioRow.id)
            if kind is not None:
                stmt = stmt.where(col(ScenarioRow.kind) == kind)
            return [_scenario(r) for r in (await db.execute(stmt)).scalars()]

        return await self._run(op)

    async def add_scenario(self, scenario: Scenario) -> Scenario:
        async def op(db: AsyncSession) -> Scenario:
            if await db.get(ScenarioRow, scenario.scenario_id) is not None:
                raise scenario_error(
                    "SCENARIO_ALREADY_EXISTS",
                    f"O cenário {scenario.scenario_id} já existe.",
                    scenario_id=scenario.scenario_id,
                )
            db.add(scenario_row(scenario))
            return scenario

        return await self._run(op, write=True)

    async def upsert_builtin(self, scenarios: Iterable[Scenario]) -> dict[str, str]:
        """Grava os cenários embutidos; devolve ``{scenario_id: inserted|updated|unchanged}``."""
        items = list(scenarios)

        async def op(db: AsyncSession) -> dict[str, str]:
            outcome: dict[str, str] = {}
            for scenario in items:
                row = await db.get(ScenarioRow, scenario.scenario_id)
                if row is None:
                    db.add(scenario_row(scenario))
                    outcome[scenario.scenario_id] = "inserted"
                elif row.scenario_sha256 != scenario.scenario_sha256 or not row.builtin:
                    content = scenario.model_dump(mode="json")
                    content["created_at"] = row.created_at.isoformat()
                    row.content_json = content
                    row.scenario_sha256 = str(scenario.scenario_sha256)
                    row.builtin = True
                    row.origin = "builtin"
                    row.kind = scenario.kind
                    outcome[scenario.scenario_id] = "updated"
                else:
                    outcome[scenario.scenario_id] = "unchanged"
            return outcome

        return await self._run(op, write=True)

    # ------------------------------------------------------------------ tentativas
    async def add_attempt(self, row: AttemptRow) -> AttemptRow:
        async def op(db: AsyncSession) -> AttemptRow:
            db.add(row)
            return row

        return await self._run(op, write=True)

    async def get_attempt(self, attempt_id: str) -> AttemptRow | None:
        async def op(db: AsyncSession) -> AttemptRow | None:
            return await db.get(AttemptRow, attempt_id)

        return await self._run(op)

    async def update_attempt(self, attempt_id: str, **changes: Any) -> AttemptRow:
        async def op(db: AsyncSession) -> AttemptRow:
            row = await db.get(AttemptRow, attempt_id)
            if row is None:
                raise scenario_error("ATTEMPT_NOT_FOUND", f"A tentativa {attempt_id} não existe.")
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = utcnow()
            await db.flush()
            return row

        return await self._run(op, write=True)

    async def open_attempts(self, scenario_id: str, profile_id: str) -> list[AttemptRow]:
        """Tentativas não terminais do perfil no cenário (RF-27)."""

        async def op(db: AsyncSession) -> list[AttemptRow]:
            stmt = select(AttemptRow).where(
                col(AttemptRow.scenario_id) == scenario_id,
                col(AttemptRow.profile_id) == profile_id,
                col(AttemptRow.state).in_(("preparing", "in_progress", "evaluating")),
            )
            return list((await db.execute(stmt)).scalars())

        return await self._run(op)

    async def attempts_in_states(self, states: Sequence[str]) -> list[AttemptRow]:
        async def op(db: AsyncSession) -> list[AttemptRow]:
            stmt = select(AttemptRow).where(col(AttemptRow.state).in_(tuple(states)))
            return list((await db.execute(stmt)).scalars())

        return await self._run(op)

    async def list_attempts(
        self,
        *,
        scenario_id: str | None,
        origin: str | None,
        profile_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[AttemptRow], str | None]:
        """Página por cursor ordenada por ``started_at`` e ``id`` decrescentes."""
        after = None if cursor is None else AttemptCursor.decode(cursor)

        async def op(db: AsyncSession) -> tuple[list[AttemptRow], str | None]:
            stmt = select(AttemptRow)
            if scenario_id is not None:
                stmt = stmt.where(col(AttemptRow.scenario_id) == scenario_id)
            if origin is not None:
                stmt = stmt.where(col(AttemptRow.origin) == origin)
            if profile_id is not None:
                stmt = stmt.where(col(AttemptRow.profile_id) == profile_id)
            if after is not None:
                started, last_id = after
                stmt = stmt.where(
                    or_(
                        col(AttemptRow.started_at) < started,
                        and_(col(AttemptRow.started_at) == started, col(AttemptRow.id) < last_id),
                    )
                )
            stmt = stmt.order_by(
                col(AttemptRow.started_at).desc(), col(AttemptRow.id).desc()
            ).limit(limit + 1)
            rows = list((await db.execute(stmt)).scalars())
            more = len(rows) > limit
            rows = rows[:limit]
            nxt = AttemptCursor.encode(rows[-1].started_at, rows[-1].id) if more and rows else None
            return rows, nxt

        return await self._run(op)

    # ------------------------------------------------------------------ puxadas
    async def runs_of(self, attempt_id: str) -> list[AttemptRunRow]:
        async def op(db: AsyncSession) -> list[AttemptRunRow]:
            stmt = select(AttemptRunRow).where(col(AttemptRunRow.attempt_id) == attempt_id)
            return list((await db.execute(stmt)).scalars())

        return await self._run(op)

    async def upsert_runs(self, rows: Sequence[AttemptRunRow]) -> None:
        async def op(db: AsyncSession) -> None:
            for row in rows:
                existing = await db.get(AttemptRunRow, (row.attempt_id, row.run_id, row.pull_index))
                if existing is None:
                    db.add(row)
                    continue
                existing.run_type = row.run_type
                existing.valid = row.valid
                existing.invalid_reason = row.invalid_reason
                existing.calibration_hash = row.calibration_hash
                existing.peak_whp = row.peak_whp
                existing.trace_json = row.trace_json

        if rows:
            await self._run(op, write=True)

    # ------------------------------------------------------------------ avaliações
    async def add_evaluation(self, row: EvaluationRow) -> EvaluationRow:
        async def op(db: AsyncSession) -> EvaluationRow:
            db.add(row)
            return row

        return await self._run(op, write=True)

    async def update_evaluation(self, evaluation_id: str, **changes: Any) -> EvaluationRow:
        async def op(db: AsyncSession) -> EvaluationRow:
            row = await db.get(EvaluationRow, evaluation_id)
            if row is None:
                raise scenario_error("EVALUATION_NOT_FOUND", "Avaliação inexistente.")
            for key, value in changes.items():
                setattr(row, key, value)
            await db.flush()
            return row

        return await self._run(op, write=True)

    async def evaluations_of(self, attempt_id: str) -> list[EvaluationRow]:
        async def op(db: AsyncSession) -> list[EvaluationRow]:
            stmt = (
                select(EvaluationRow)
                .where(col(EvaluationRow.attempt_id) == attempt_id)
                .order_by(col(EvaluationRow.submission_index))
            )
            return list((await db.execute(stmt)).scalars())

        return await self._run(op)

    async def latest_evaluations(self, attempt_ids: Sequence[str]) -> dict[str, EvaluationRow]:
        if not attempt_ids:
            return {}

        async def op(db: AsyncSession) -> dict[str, EvaluationRow]:
            stmt = select(EvaluationRow).where(
                col(EvaluationRow.attempt_id).in_(tuple(attempt_ids))
            )
            latest: dict[str, EvaluationRow] = {}
            for row in (await db.execute(stmt)).scalars():
                cur = latest.get(row.attempt_id)
                if cur is None or row.submission_index > cur.submission_index:
                    latest[row.attempt_id] = row
            return latest

        return await self._run(op)

    async def pending_evaluations(self, older_than: datetime) -> list[EvaluationRow]:
        async def op(db: AsyncSession) -> list[EvaluationRow]:
            stmt = select(EvaluationRow).where(
                col(EvaluationRow.status) == "pending", col(EvaluationRow.created_at) < older_than
            )
            return list((await db.execute(stmt)).scalars())

        return await self._run(op)

    async def last_passed_by_profile(self, profile_id: str) -> dict[str, bool]:
        """``{scenario_id: passed}`` da última avaliação concluída do perfil por cenário."""

        async def op(db: AsyncSession) -> dict[str, bool]:
            stmt = (
                select(
                    col(AttemptRow.scenario_id),
                    col(EvaluationRow.passed),
                    col(EvaluationRow.created_at),
                )
                .join(EvaluationRow, col(EvaluationRow.attempt_id) == AttemptRow.id)
                .where(
                    col(AttemptRow.profile_id) == profile_id,
                    col(EvaluationRow.status) == "completed",
                )
                .order_by(col(EvaluationRow.created_at))
            )
            result: dict[str, bool] = {}
            for scenario_id, passed, _created in (await db.execute(stmt)).all():
                result[str(scenario_id)] = bool(passed)
            return result

        return await self._run(op)

    # ------------------------------------------------------------------ eventos
    async def add_event(
        self, kind: str, scenario_id: str, attempt_id: str, data: dict[str, Any] | None = None
    ) -> ScenarioEventRow:
        payload = dict(data or {})
        if _contains_pii(payload):
            raise ValueError("scenario_event.data_json não pode conter PII (nickname)")
        row = ScenarioEventRow(
            id=str(uuid.uuid4()),
            kind=kind,
            scenario_id=scenario_id,
            attempt_id=attempt_id,
            data_json=payload,
            created_at=utcnow(),
        )

        async def op(db: AsyncSession) -> ScenarioEventRow:
            db.add(row)
            return row

        return await self._run(op, write=True)

    async def events(
        self,
        *,
        scenario_ids: Sequence[str] | None = None,
        kinds: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        attempt_id: str | None = None,
    ) -> list[ScenarioEventRow]:
        async def op(db: AsyncSession) -> list[ScenarioEventRow]:
            stmt = select(ScenarioEventRow)
            if scenario_ids is not None:
                stmt = stmt.where(col(ScenarioEventRow.scenario_id).in_(tuple(scenario_ids)))
            if kinds is not None:
                stmt = stmt.where(col(ScenarioEventRow.kind).in_(tuple(kinds)))
            if start is not None:
                stmt = stmt.where(col(ScenarioEventRow.created_at) >= start)
            if end is not None:
                stmt = stmt.where(col(ScenarioEventRow.created_at) <= end)
            if attempt_id is not None:
                stmt = stmt.where(col(ScenarioEventRow.attempt_id) == attempt_id)
            stmt = stmt.order_by(col(ScenarioEventRow.created_at), col(ScenarioEventRow.id))
            return list((await db.execute(stmt)).scalars())

        return await self._run(op)

    # ------------------------------------------------------------------ pacotes
    async def imported_package(self, sha256: str) -> ImportedPackageRow | None:
        async def op(db: AsyncSession) -> ImportedPackageRow | None:
            return await db.get(ImportedPackageRow, sha256)

        return await self._run(op)

    async def import_bundle(self, bundle: ImportBundle) -> None:
        """Grava o pacote e as linhas derivadas numa transação (revertida em erro)."""

        async def op(db: AsyncSession) -> None:
            if bundle.scenario is not None:
                db.add(bundle.scenario)
            if bundle.attempt is not None:
                if bundle.replace_attempt:
                    attempt_id = bundle.attempt.id
                    await db.execute(
                        delete(AttemptRunRow).where(col(AttemptRunRow.attempt_id) == attempt_id)
                    )
                    await db.execute(
                        delete(EvaluationRow).where(col(EvaluationRow.attempt_id) == attempt_id)
                    )
                    old = await db.get(AttemptRow, attempt_id)
                    if old is not None:
                        await db.delete(old)
                    await db.flush()
                db.add(bundle.attempt)
                await db.flush()
                for run in bundle.runs:
                    db.add(run)
                if bundle.evaluation is not None:
                    db.add(bundle.evaluation)
            db.add(bundle.package)

        await self._run(op, write=True)


# --------------------------------------------------------------------------- conversões


def _profile(row: PlayerProfileRow) -> PlayerProfile:
    return PlayerProfile(
        profile_id=row.id, nickname=row.nickname, role=Role(row.role), created_at=row.created_at
    )


def _scenario(row: ScenarioRow) -> Scenario:
    data = dict(row.content_json)
    data.update(
        {
            "scenario_sha256": row.scenario_sha256,
            "builtin": row.builtin,
            "origin": row.origin,
            "created_at": row.created_at.isoformat(),
        }
    )
    return Scenario.model_validate(data)


def scenario_row(scenario: Scenario) -> ScenarioRow:
    created = scenario.created_at or utcnow()
    content = scenario.model_dump(mode="json")
    content["created_at"] = created.isoformat()
    return ScenarioRow(
        id=scenario.scenario_id,
        kind=scenario.kind,
        builtin=scenario.builtin,
        origin=scenario.origin,
        scenario_sha256=str(scenario.scenario_sha256),
        content_json=content,
        created_at=created,
    )
