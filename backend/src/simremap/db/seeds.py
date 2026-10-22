"""Seeds idempotentes da fundação em ``app_meta`` (data-model 6.3; T407).

Executados no lifespan depois de ``alembic upgrade head`` (nenhuma migração insere dados):

- ``install_id``: UUID4 aleatório da estação, inserido só no 1.º arranque e nunca
  alterado (sem relação com pessoa).
- ``schema_created_at``: ISO-8601 UTC do 1.º arranque; nunca alterado.
- ``last_boot_app_version``: upsert com a ``app_version`` de cada arranque.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from simremap.db.base import utcnow
from simremap.db.models.foundation import AppMeta

__all__ = ["FoundationSeed", "has_app_meta", "seed_app_meta"]


@dataclass(frozen=True, slots=True)
class FoundationSeed:
    install_id: str
    schema_created_at: str
    last_boot_app_version: str
    created: bool


def _has_table(connection: Connection) -> bool:
    return bool(inspect(connection).has_table(AppMeta.__tablename__))


async def has_app_meta(engine: AsyncEngine) -> bool:
    """``True`` se a tabela ``app_meta`` existe (banco migrado)."""
    async with engine.connect() as conn:
        return await conn.run_sync(_has_table)


async def seed_app_meta(
    maker: async_sessionmaker[AsyncSession], app_version: str
) -> FoundationSeed:
    """Aplica os 3 seeds da fundação numa transação e devolve os valores finais."""
    async with maker() as session, session.begin():
        install = await session.get(AppMeta, "install_id")
        created = install is None
        if install is None:
            install = AppMeta(key="install_id", value=str(uuid.uuid4()))
            session.add(install)
        schema = await session.get(AppMeta, "schema_created_at")
        if schema is None:
            schema = AppMeta(key="schema_created_at", value=utcnow().isoformat())
            session.add(schema)
        boot = await session.get(AppMeta, "last_boot_app_version")
        if boot is None:
            boot = AppMeta(key="last_boot_app_version", value=app_version)
            session.add(boot)
        elif boot.value != app_version:
            boot.value = app_version
            boot.updated_at = utcnow()
        return FoundationSeed(
            install_id=install.value,
            schema_created_at=schema.value,
            last_boot_app_version=boot.value,
            created=created,
        )
