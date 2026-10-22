"""Persistência do Modo Carreira (``career_profiles`` e ``career_jobs``, migração 0008).

Uma transação por operação. A liquidação grava o job e o perfil juntos e só muda um job
``accepted`` (idempotente: o segundo pedido devolve o job já liquidado).
Falha do banco ⇒ 503 ``DATABASE_UNAVAILABLE`` com ``Retry-After: 2``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col

from simremap.career.contracts import (
    REPUTATION_MAX,
    CareerJob,
    CareerProfile,
    JobStatus,
)
from simremap.career.errors import career_error
from simremap.core.errors import SimRemapError
from simremap.db.models.career import CareerJobRow, CareerProfileRow

__all__ = ["CareerRepository", "Settlement"]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Settlement:
    """Resultado calculado pelo serviço para um job ``accepted``."""

    status: JobStatus
    delta_balance_brl: int  # centavos
    reputation_change: int  # pedido; o perfil fica limitado a 0–100
    settled_at: datetime


def _unavailable() -> SimRemapError:
    return SimRemapError(
        "Banco de dados indisponível.", code="DATABASE_UNAVAILABLE", headers={"Retry-After": "2"}
    )


def profile_of(row: CareerProfileRow) -> CareerProfile:
    return CareerProfile.model_validate(row, from_attributes=True)


def job_of(row: CareerJobRow) -> CareerJob:
    return CareerJob.model_validate(row, from_attributes=True)


class CareerRepository:
    def __init__(self, maker: async_sessionmaker[AsyncSession] | None) -> None:
        self._maker = maker

    async def _run(self, op: Callable[[AsyncSession], Awaitable[T]], *, write: bool = False) -> T:
        if self._maker is None:
            raise _unavailable()
        try:
            async with self._maker() as db:
                result = await op(db)
                if write:
                    await db.commit()
                return result
        except (SimRemapError, IntegrityError):
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    # ------------------------------------------------------------------ perfis
    async def ensure_profile(self, profile_id: str) -> CareerProfile:
        """Perfil da carreira; criado com o saldo e a reputação iniciais se não existir."""

        async def op(db: AsyncSession) -> CareerProfile:
            row = await db.get(CareerProfileRow, profile_id)
            if row is None:
                row = CareerProfileRow(profile_id=profile_id)
                db.add(row)
                await db.flush()
            return profile_of(row)

        try:
            return await self._run(op, write=True)
        except IntegrityError:  # criado em paralelo por outro pedido
            return await self._run(op)

    # ------------------------------------------------------------------ jobs
    async def add_job(self, row: CareerJobRow) -> CareerJob:
        async def op(db: AsyncSession) -> CareerJob:
            db.add(row)
            await db.flush()
            return job_of(row)

        return await self._run(op, write=True)

    async def get_job(self, job_id: str) -> CareerJob | None:
        async def op(db: AsyncSession) -> CareerJob | None:
            row = await db.get(CareerJobRow, job_id)
            return None if row is None else job_of(row)

        return await self._run(op)

    async def open_job(self, profile_id: str) -> CareerJob | None:
        async def op(db: AsyncSession) -> CareerJob | None:
            stmt = select(CareerJobRow).where(
                col(CareerJobRow.profile_id) == profile_id,
                col(CareerJobRow.status) == JobStatus.ACCEPTED.value,
            )
            row = (await db.execute(stmt.limit(1))).scalars().first()
            return None if row is None else job_of(row)

        return await self._run(op)

    async def list_jobs(self, profile_id: str) -> list[CareerJob]:
        async def op(db: AsyncSession) -> list[CareerJob]:
            stmt = (
                select(CareerJobRow)
                .where(col(CareerJobRow.profile_id) == profile_id)
                .order_by(col(CareerJobRow.accepted_at).desc(), col(CareerJobRow.job_id))
            )
            return [job_of(r) for r in (await db.execute(stmt)).scalars()]

        return await self._run(op)

    async def settle(self, job_id: str, settlement: Settlement) -> CareerJob:
        """Aplica a liquidação ao job e ao perfil numa transação (só job ``accepted``)."""

        async def op(db: AsyncSession) -> CareerJob:
            job = await db.get(CareerJobRow, job_id)
            if job is None:
                raise career_error("CAREER_JOB_NOT_FOUND", f"O serviço {job_id} não existe.")
            if job.status != JobStatus.ACCEPTED.value:
                return job_of(job)
            profile = await db.get(CareerProfileRow, job.profile_id)
            if profile is None:
                raise career_error(
                    "CAREER_JOB_NOT_FOUND", f"O serviço {job_id} não tem perfil da carreira."
                )
            reputation = min(
                max(profile.reputation + settlement.reputation_change, 0), REPUTATION_MAX
            )
            job.status = settlement.status.value
            job.delta_balance_brl = settlement.delta_balance_brl
            job.delta_reputation = reputation - profile.reputation
            job.settled_at = settlement.settled_at
            profile.balance_brl += settlement.delta_balance_brl
            profile.reputation = reputation
            profile.updated_at = settlement.settled_at
            await db.flush()
            return job_of(job)

        return await self._run(op, write=True)
