"""Engine assíncrono e sessão por pedido (T087, T229; RF-09; D-09)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlmodel import col, select

from simremap.api.deps import SessionDep
from simremap.api.main import create_app
from simremap.core.config import Settings
from simremap.db.engine import SQLITE_PRAGMAS, build_engine, build_sessionmaker
from simremap.db.models.foundation import AppMeta


async def test_sqlite_pragmas_on_every_connection(settings: Settings) -> None:
    engine = build_engine(settings)
    try:
        for _ in range(2):
            async with engine.connect() as conn:
                journal = (await conn.execute(sa.text("PRAGMA journal_mode"))).scalar_one()
                fks = (await conn.execute(sa.text("PRAGMA foreign_keys"))).scalar_one()
                busy = (await conn.execute(sa.text("PRAGMA busy_timeout"))).scalar_one()
                sync = (await conn.execute(sa.text("PRAGMA synchronous"))).scalar_one()
            assert (journal, fks, busy, sync) == ("wal", 1, 5000, 1)
    finally:
        await engine.dispose()
    assert "PRAGMA synchronous=NORMAL" in SQLITE_PRAGMAS


async def test_sqlite_parent_dir_is_created(settings_factory: Any, tmp_path: Any) -> None:
    target = tmp_path / "novo" / "sub" / "x.db"
    engine = build_engine(settings_factory(database_url=f"sqlite+aiosqlite:///{target}"))
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    finally:
        await engine.dispose()
    assert target.exists()


def test_postgres_engine_uses_pool(settings_factory: Any) -> None:
    engine = build_engine(
        settings_factory(database_url="postgresql+asyncpg://u:p@127.0.0.1:1/db", db_pool_size=7)
    )
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.pool.size() == 7  # type: ignore[attr-defined]
        assert engine.pool._pre_ping is True
    finally:
        engine.sync_engine.dispose()


async def test_sessionmaker_keeps_objects_after_commit(settings: Settings) -> None:
    from simremap.db.migrate import upgrade_engine

    engine = build_engine(settings)
    await upgrade_engine(engine)
    maker = build_sessionmaker(engine)
    try:
        async with maker() as session:
            row = AppMeta(key="probe", value="v")
            session.add(row)
            await session.commit()
            assert row.value == "v"  # expire_on_commit=False
    finally:
        await engine.dispose()


def _write_app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.post("/api/v1/_probe/write/{key}")
    async def write(key: str, session: SessionDep, fail: bool = False) -> dict[str, str]:
        session.add(AppMeta(key=key, value="v"))
        await session.flush()
        if fail:
            raise RuntimeError("falha depois do flush")
        await session.commit()
        return {"key": key}

    @app.get("/api/v1/_probe/count")
    async def count(session: SessionDep) -> dict[str, int]:
        rows = (await session.execute(select(AppMeta).where(col(AppMeta.key).like("k-%")))).all()
        return {"n": len(rows)}

    return app


async def test_rollback_and_100_concurrent_writes(settings: Settings) -> None:
    app = _write_app(settings)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            failed = await ac.post("/api/v1/_probe/write/k-falha", params={"fail": "true"})
            assert failed.status_code == 500
            assert (await ac.get("/api/v1/_probe/count")).json() == {"n": 0}
            responses = await asyncio.gather(
                *(ac.post(f"/api/v1/_probe/write/k-{i}") for i in range(100))
            )
            statuses = {r.status_code for r in responses}
            assert statuses == {200}, [r.text for r in responses if r.status_code != 200][:2]
            assert (await ac.get("/api/v1/_probe/count")).json() == {"n": 100}


@pytest.mark.parametrize("url", ["sqlite+aiosqlite:///:memory:"])
async def test_memory_database_shares_one_connection(settings_factory: Any, url: str) -> None:
    engine = build_engine(settings_factory(database_url=url))
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text("CREATE TABLE t (x INTEGER)"))
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT count(*) FROM t"))).scalar_one() == 0
    finally:
        await engine.dispose()
