"""Engine assíncrono e sessão por pedido (platform-foundation RF-09, D-09).

- SQLite (``sqlite+aiosqlite``): ``timeout=5`` e, em cada ligação, ``PRAGMA
  journal_mode=WAL``, ``foreign_keys=ON``, ``busy_timeout=5000``, ``synchronous=NORMAL``.
  ``:memory:`` usa ``StaticPool`` (uma ligação partilhada).
- PostgreSQL (``postgresql+asyncpg``): ``pool_size`` de ``Settings`` e ``pool_pre_ping``.
- ``get_session``: dependência FastAPI; ``expire_on_commit=False``, commit explícito
  pelo chamador, rollback automático em exceção e ``close`` no fim do pedido.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from simremap.core.config import Settings

__all__ = ["SQLITE_PRAGMAS", "build_engine", "build_sessionmaker", "get_session"]

SQLITE_PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
)


def _apply_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def build_engine(settings: Settings) -> AsyncEngine:
    """Cria o ``AsyncEngine`` conforme o driver de ``settings.db_url``."""
    url = settings.db_url
    if settings.is_sqlite:
        if settings.sqlite_path is None:
            engine = create_async_engine(
                url,
                connect_args={"timeout": 5, "check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_async_engine(url, connect_args={"timeout": 5})
        event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
        return engine
    return create_async_engine(url, pool_size=settings.db_pool_size, pool_pre_ping=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Sessão por pedido a partir de ``app.state.sessionmaker`` (criado no lifespan)."""
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
