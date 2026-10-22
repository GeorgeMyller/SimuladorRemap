"""Migração automática com cópia de segurança (T088 parte backup, T230; RF-10; data-model 5.6)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager

from simremap.api.main import create_app
from simremap.db.engine import build_engine
from simremap.db.migrate import (
    BACKUP_KEEP,
    backup_sqlite,
    current_revision,
    migrate_on_startup,
    pending_revisions,
    script_head,
    upgrade,
)

FIRST = "0001_foundation_base"


def _make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    conn.close()


def test_backup_copies_and_keeps_last_three(tmp_path: Path) -> None:
    db = tmp_path / "simremap.db"
    _make_db(db)
    backup_dir = tmp_path / "backup"
    base = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    made = [
        backup_sqlite(db, backup_dir, "0.1.0", now=base + timedelta(seconds=i)) for i in range(5)
    ]
    remaining = sorted(p.name for p in backup_dir.iterdir())
    assert len(remaining) == BACKUP_KEEP == 3
    assert remaining == sorted(p.name for p in made[-3:])
    assert remaining[0].startswith("simremap-0.1.0-20261018T120002")
    copy = sqlite3.connect(made[-1])
    assert copy.execute("SELECT count(*) FROM t").fetchone() == (3,)
    copy.close()
    (backup_dir / "outro-ficheiro.db").write_text("x")
    backup_sqlite(db, backup_dir, "0.2.0", now=base + timedelta(seconds=10))
    assert (backup_dir / "outro-ficheiro.db").exists()  # só os backups com o padrão são podados


async def test_pending_and_current_revision(settings_factory: Any, tmp_path: Path) -> None:
    db = tmp_path / "simremap.db"
    url = f"sqlite+aiosqlite:///{db}"
    engine = build_engine(settings_factory(database_url=url))
    try:
        assert await current_revision(engine) is None
        pending = await pending_revisions(engine)
        assert pending[0] == FIRST and pending[-1] == script_head()
        await asyncio.to_thread(upgrade, url, FIRST)
        assert await current_revision(engine) == FIRST
        assert FIRST not in await pending_revisions(engine)
        await asyncio.to_thread(upgrade, url)
        assert await pending_revisions(engine) == []
    finally:
        await engine.dispose()


async def test_fresh_database_has_no_backup(settings_factory: Any, tmp_path: Path) -> None:
    settings = settings_factory()
    engine = build_engine(settings)
    try:
        result = await migrate_on_startup(engine, settings)
    finally:
        await engine.dispose()
    assert result.backup is None
    assert result.head == script_head()
    assert result.applied[-1] == script_head()
    assert not (tmp_path / "backup").exists()


async def test_backup_before_upgrade_with_pending_revisions(
    settings_factory: Any, tmp_path: Path
) -> None:
    if script_head() == FIRST:
        pytest.skip("a cadeia só tem a revisão 0001")
    settings = settings_factory()
    await asyncio.to_thread(upgrade, settings.db_url, FIRST)
    app = create_app(settings)
    async with LifespanManager(app):
        pass
    backups = list((tmp_path / "backup").glob("simremap-0.1.0-*.db"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    version = copy.execute("SELECT version_num FROM alembic_version").fetchone()
    copy.close()
    assert version == (FIRST,)  # a cópia é do estado anterior ao upgrade
    # Segundo arranque: nada pendente, nenhum backup novo.
    async with LifespanManager(create_app(settings)):
        pass
    assert len(list((tmp_path / "backup").iterdir())) == 1


async def test_postgres_never_backed_up(settings_factory: Any) -> None:
    settings = settings_factory(database_url="postgresql+asyncpg://u:p@127.0.0.1:1/db")
    assert settings.sqlite_path is None
