"""Matriz de migrações em PostgreSQL 16 (T188; D-09; platform OQ-04; RF-10).

Corre só com ``-m postgres`` e ``SIMREMAP_TEST_POSTGRES_URL`` definido, por exemplo::

    docker compose -f compose.yaml --profile postgres up -d postgres
    SIMREMAP_TEST_POSTGRES_URL=postgresql+asyncpg://simremap:simremap@127.0.0.1:5432/simremap \\
        uv run pytest -m postgres tests/integration/test_migrations_postgres.py

(``make test-postgres`` faz o mesmo). O banco indicado é limpo (``downgrade base``).
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import create_async_engine

from simremap.api.main import create_app
from simremap.db.migrate import downgrade, script_head, script_heads, upgrade
from simremap.db.models import metadata

pytestmark = pytest.mark.postgres

URL = os.environ.get("SIMREMAP_TEST_POSTGRES_URL", "")
requires_pg = pytest.mark.skipif(
    not URL.startswith("postgresql+asyncpg://"),
    reason="defina SIMREMAP_TEST_POSTGRES_URL=postgresql+asyncpg://...",
)


async def _tables_and_version() -> tuple[set[str], str | None, str]:
    engine = create_async_engine(URL)
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
            version = None
            if "alembic_version" in names:
                version = (
                    await conn.execute(sa.text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
            server = (await conn.execute(sa.text("SHOW server_version"))).scalar_one()
    finally:
        await engine.dispose()
    return names, version, str(server)


def test_single_head() -> None:
    assert len(script_heads()) == 1


@requires_pg
async def test_downgrade_base_then_upgrade_head() -> None:
    await asyncio.to_thread(upgrade, URL)
    await asyncio.to_thread(downgrade, URL, "base")
    names, version, server = await _tables_and_version()
    assert server.split(".")[0] == "16"
    assert names <= {"alembic_version"}
    assert version is None
    await asyncio.to_thread(upgrade, URL)
    names, version, _ = await _tables_and_version()
    assert set(metadata.tables) <= names
    assert version == script_head()


@requires_pg
async def test_lifespan_on_postgres(settings_factory: object) -> None:
    settings = settings_factory(database_url=URL)  # type: ignore[operator]
    app = create_app(settings)
    async with LifespanManager(app, startup_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://pg") as ac:
            health = (await ac.get("/api/v1/health")).json()
            version = (await ac.get("/api/v1/version")).json()
        assert app.state.install_id
    assert health["checks"]["database"]["status"] == "ok"
    assert version["alembic_head"] == script_head()
