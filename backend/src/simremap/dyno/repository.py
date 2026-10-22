"""Persistência de ``simulation_session`` e ``dyno_run`` (dyno RF-18; EC-04; data-model 2.2).

Cada escrita tenta 1 + 3 vezes com espera de 100, 200 e 400 ms; persistindo a falha, o
método devolve ``False`` e o chamador mantém o objeto em memória com
``persisted = false`` (EC-04). Leituras com o banco indisponível devolvem ``None``.

A curva suavizada não é persistida: ``curve_raw_json`` guarda a curva bruta agregada e a
suavização é recalculada na leitura com a janela do pedido (seção 15).

Flex (002): a coluna ``fuel_id`` só aceita combustíveis do catálogo (CHECK da migração
0002); uma sessão ``flex`` grava a âncora mais próxima (``e27``/``e100``) na coluna e o
``fuel_id`` efetivo, ``ethanol_pct`` e ``upgrades`` em ``config_json``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from simremap.catalog.contracts import FUEL_IDS
from simremap.core.logging import get_logger
from simremap.db.models.dyno import DynoRunRow, SimulationSessionRow
from simremap.dyno.contracts import DynoRun, SimulationSession

__all__ = [
    "RETRY_DELAYS_S",
    "DynoRepository",
    "column_fuel_id",
    "session_config",
    "session_from_row",
]

log = get_logger("simremap.dyno")

RETRY_DELAYS_S: Final = (0.1, 0.2, 0.4)
_CONFIG_FIELDS: Final = (
    "ambient",
    "correction_standard",
    "rig",
    "operator_protection",
    "egt_abort_enabled",
    "damage_enabled",
    "physics_faults",
    "upgrades",
    "ethanol_pct",
)
_ACTIVE_CALIBRATION_FIELDS: Final = ("active_calibration_id", "active_calibration_version")
_RESTORED_CONFIG_FIELDS: Final = (
    *_CONFIG_FIELDS,
    *_ACTIVE_CALIBRATION_FIELDS,
    "ecu_state",
    "fuel_id",
)
FLEX_COLUMN_SPLIT_PCT: Final = 63.5  # % : abaixo grava "e27", acima "e100"


def session_config(session: SimulationSession) -> dict[str, Any]:
    """``config_json`` da sessão (ambiente, rolo, correção, flags e defeitos)."""
    data = session.model_dump(mode="json")
    config = {name: data[name] for name in _CONFIG_FIELDS}
    config["ecu_state"] = data["ecu_state"]
    for name in _ACTIVE_CALIBRATION_FIELDS:
        if data[name] is not None:
            config[name] = data[name]
    if session.fuel_id not in FUEL_IDS:
        config["fuel_id"] = session.fuel_id
    return config


def column_fuel_id(session: SimulationSession) -> str:
    """Valor da coluna ``fuel_id`` (sempre do catálogo; ``flex`` vira a âncora mais próxima)."""
    if session.fuel_id in FUEL_IDS:
        return session.fuel_id
    pct = session.ethanol_pct if session.ethanol_pct is not None else 100.0
    return "e27" if pct < FLEX_COLUMN_SPLIT_PCT else "e100"


def _aware(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def session_from_row(row: SimulationSessionRow) -> SimulationSession:
    """``SimulationSession`` reconstruída da linha (sessões encerradas ou após reinício)."""
    config = dict(row.config_json)
    return SimulationSession.model_validate(
        {
            "vehicle_id": row.vehicle_id,
            "calibration_id": row.calibration_id,
            "profile_id": row.profile_id,
            "seed": row.seed,
            "sim_hz": row.sim_hz,
            "fuel_id": row.fuel_id,
            "attempt_id": row.attempt_id,
            "session_id": row.session_id,
            "state": row.state,
            "baseline_run_id": row.baseline_run_id,
            "engine_locked": row.state == "engine_locked",
            "created_at": _aware(row.created_at),
            **{k: v for k, v in config.items() if k in _RESTORED_CONFIG_FIELDS},
        }
    )


def _run_from_row(row: DynoRunRow, session: SimulationSessionRow) -> DynoRun:
    return DynoRun.model_validate(
        {
            "run_id": row.run_id,
            "session_id": row.session_id,
            "run_type": row.run_type,
            "request": row.request_json,
            "state": row.state,
            "abort_reason": row.abort_reason,
            "started_at_tick": row.started_at_tick,
            "ended_at_tick": row.ended_at_tick,
            "calibration_id": row.calibration_id,
            "calibration_hash": row.calibration_hash,
            "seed": session.seed,
            "sim_hz": session.sim_hz,
            "summary": row.summary_json,
            "curve": row.curve_raw_json,
            "pulls": row.pulls_json or [],
            "repeatability": row.repeatability_json,
            "curve_sha256": row.curve_sha256,
        }
    )


class DynoRepository:
    """Leitura e escrita das sessões e puxadas com novas tentativas."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None,
        *,
        retry_delays_s: Sequence[float] = RETRY_DELAYS_S,
    ) -> None:
        self._maker = sessionmaker
        self._retry = tuple(retry_delays_s)

    @property
    def available(self) -> bool:
        return self._maker is not None

    async def _write(
        self, op: Callable[[AsyncSession], Awaitable[None]], table: str, **context: object
    ) -> bool:
        if self._maker is None:
            return False
        for delay in (*self._retry, None):
            try:
                async with self._maker() as session:
                    await op(session)
                    await session.commit()
                return True
            except SQLAlchemyError as exc:
                log.warning("dyno.persist_failed", table=table, error=type(exc).__name__, **context)
                if delay is None:
                    return False
                await asyncio.sleep(delay)
        return False  # pragma: no cover - o laço sempre retorna

    # ------------------------------------------------------------------ sessões
    async def save_session(
        self, session: SimulationSession, *, data_version: int, catalog_sha256: str
    ) -> bool:
        async def op(db: AsyncSession) -> None:
            row = await db.get(SimulationSessionRow, session.session_id)
            if row is None:
                row = SimulationSessionRow(
                    session_id=session.session_id,
                    vehicle_id=session.vehicle_id,
                    data_version=data_version,
                    catalog_sha256=catalog_sha256,
                    calibration_id=session.calibration_id,
                    profile_id=session.profile_id,
                    fuel_id=column_fuel_id(session),
                    seed=session.seed,
                    sim_hz=session.sim_hz,
                    attempt_id=session.attempt_id,
                    config_json=session_config(session),
                    state=session.state,
                    baseline_run_id=session.baseline_run_id,
                    created_at=session.created_at,
                )
            else:
                row.state = session.state
                row.baseline_run_id = session.baseline_run_id
                row.config_json = session_config(session)
                if session.state == "closed" and row.closed_at is None:
                    row.closed_at = datetime.now(UTC)
            db.add(row)

        return await self._write(op, "simulation_session", session_id=session.session_id)

    async def get_session(self, session_id: str) -> SimulationSession | None:
        if self._maker is None:
            return None
        try:
            async with self._maker() as db:
                row = await db.get(SimulationSessionRow, session_id)
        except SQLAlchemyError:
            return None
        return None if row is None else session_from_row(row)

    async def close_stale_sessions(self) -> int:
        """Fecha sessões ``ready``/``running`` órfãs de um arranque anterior (worker perdido)."""
        if self._maker is None:
            return 0
        closed = 0
        try:
            async with self._maker() as db:
                result = await db.execute(
                    select(SimulationSessionRow).where(
                        col(SimulationSessionRow.state).in_(("ready", "running", "engine_locked"))
                    )
                )
                for row in result.scalars():
                    row.state = "closed"
                    row.closed_at = datetime.now(UTC)
                    db.add(row)
                    closed += 1
                runs = await db.execute(
                    select(DynoRunRow).where(
                        col(DynoRunRow.state).in_(("idle", "arming", "running", "coastdown"))
                    )
                )
                for run in runs.scalars():
                    run.state = "aborted"
                    run.abort_reason = "session_closed"
                    db.add(run)
                await db.commit()
        except SQLAlchemyError as exc:
            log.warning("dyno.close_stale_failed", error=type(exc).__name__)
            return 0
        return closed

    # ------------------------------------------------------------------ puxadas
    async def save_run(self, run: DynoRun) -> bool:
        data = run.model_dump(mode="json", by_alias=True)

        async def op(db: AsyncSession) -> None:
            row = await db.get(DynoRunRow, run.run_id)
            if row is None:
                row = DynoRunRow(
                    run_id=run.run_id,
                    session_id=run.session_id,
                    run_type=run.run_type.value,
                    calibration_id=run.calibration_id,
                    calibration_hash=run.calibration_hash,
                    request_json=data["request"],
                    started_at_tick=run.started_at_tick,
                )
            row.state = run.state.value
            row.abort_reason = None if run.abort_reason is None else run.abort_reason.value
            row.summary_json = data["summary"]
            row.curve_raw_json = data["curve"]
            row.pulls_json = data["pulls"] or None
            row.repeatability_json = data["repeatability"]
            row.curve_sha256 = run.curve_sha256
            row.calibration_hash = run.calibration_hash
            row.started_at_tick = run.started_at_tick
            row.ended_at_tick = run.ended_at_tick
            db.add(row)

        return await self._write(op, "dyno_run", run_id=run.run_id)

    async def get_run(self, run_id: str) -> DynoRun | None:
        if self._maker is None:
            return None
        try:
            async with self._maker() as db:
                row = await db.get(DynoRunRow, run_id)
                session = (
                    None if row is None else await db.get(SimulationSessionRow, row.session_id)
                )
        except SQLAlchemyError:
            return None
        if row is None or session is None:
            return None
        return _run_from_row(row, session)

    async def runs_of(self, session_id: str) -> list[DynoRun]:
        if self._maker is None:
            return []
        try:
            async with self._maker() as db:
                result = await db.execute(
                    select(DynoRunRow)
                    .where(col(DynoRunRow.session_id) == session_id)
                    .order_by(col(DynoRunRow.created_at), col(DynoRunRow.run_id))
                )
                rows = list(result.scalars())
                session = await db.get(SimulationSessionRow, session_id)
        except SQLAlchemyError:
            return []
        if session is None:
            return []
        return [_run_from_row(r, session) for r in rows]
