"""Utilitários Alembic independentes do diretório atual (platform-foundation RF-10).

- ``alembic_config(url)``: ``Config`` programático apontando para ``simremap/db/migrations``.
- ``script_head()``: revisão head da cadeia em disco (``alembic heads``).
- ``upgrade_engine(engine)``: aplica ``upgrade head`` na ligação do engine da app
  (funciona também com SQLite ``:memory:`` + ``StaticPool``).
- ``upgrade``/``downgrade`` síncronos para scripts e testes.
- ``current_revision(engine)`` / ``pending_revisions(engine)``: estado do banco.
- ``backup_sqlite(...)``: cópia de segurança antes de um ``upgrade`` com revisões
  pendentes (data-model 5.6; T230): ``<data_dir>/backup/simremap-<versão>-<timestamp>.db``
  pela API de backup do SQLite (consistente com WAL); mantém as 3 últimas. Só SQLite;
  em PostgreSQL o backup é responsabilidade do operador.
- ``migrate_on_startup(engine, settings)``: backup (se aplicável) + ``upgrade head``.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from simremap.core.logging import get_logger

if TYPE_CHECKING:
    from simremap.core.config import Settings

__all__ = [
    "BACKUP_KEEP",
    "MIGRATIONS_DIR",
    "MigrationResult",
    "alembic_config",
    "backup_sqlite",
    "current_revision",
    "downgrade",
    "migrate_on_startup",
    "pending_revisions",
    "script_head",
    "script_heads",
    "upgrade",
    "upgrade_engine",
]

MIGRATIONS_DIR: Final = Path(__file__).resolve().parent / "migrations"
BACKUP_KEEP: Final = 3
_BACKUP_NAME: Final = re.compile(r"^simremap-(?P<version>.+)-(?P<ts>\d{8}T\d{12}Z)\.db$")

log = get_logger("simremap.db.migrate")


def alembic_config(database_url: str | None = None, connection: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("version_path_separator", "os")
    if database_url is not None:
        cfg.attributes["database_url"] = database_url
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def script_heads() -> tuple[str, ...]:
    """Todas as heads da cadeia em disco (deve haver exatamente 1)."""
    return tuple(ScriptDirectory.from_config(alembic_config()).get_heads())


@lru_cache(maxsize=1)
def script_head() -> str:
    """Head única da cadeia; ``RuntimeError`` se houver ramos."""
    heads = script_heads()
    if len(heads) != 1:
        raise RuntimeError(f"cadeia Alembic deve ter 1 head, encontrou {len(heads)}: {heads}")
    return heads[0]


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(database_url), revision)


def _upgrade_on_connection(connection: Connection, revision: str) -> None:
    command.upgrade(alembic_config(connection=connection), revision)


async def upgrade_engine(engine: AsyncEngine, revision: str = "head") -> None:
    """Aplica as migrações pendentes usando uma ligação do próprio engine da app."""
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade_on_connection, revision)


def _current_on_connection(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def current_revision(engine: AsyncEngine) -> str | None:
    """Revisão atual gravada em ``alembic_version`` (``None`` em banco vazio)."""
    async with engine.connect() as conn:
        return await conn.run_sync(_current_on_connection)


async def pending_revisions(engine: AsyncEngine) -> list[str]:
    """Revisões entre a atual e a head, da mais antiga para a mais nova."""
    current = await current_revision(engine)
    script = ScriptDirectory.from_config(alembic_config())
    revisions = [rev.revision for rev in script.iterate_revisions("heads", current)]
    return list(reversed(revisions))


def _prune_backups(backup_dir: Path, keep: int) -> list[Path]:
    entries = []
    for path in backup_dir.glob("simremap-*.db"):
        match = _BACKUP_NAME.match(path.name)
        if match is not None:
            entries.append((match.group("ts"), path))
    entries.sort()
    removed = [path for _, path in entries[: max(0, len(entries) - keep)]]
    for path in removed:
        path.unlink(missing_ok=True)
    return removed


def backup_sqlite(
    db_path: Path,
    backup_dir: Path,
    app_version: str,
    *,
    keep: int = BACKUP_KEEP,
    now: datetime | None = None,
) -> Path:
    """Copia ``db_path`` para ``backup_dir`` (API de backup do SQLite) e mantém ``keep`` cópias."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"simremap-{app_version}-{stamp}.db"
    source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        dest = sqlite3.connect(target.as_posix())
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    _prune_backups(backup_dir, keep)
    return target


class MigrationResult:
    """Resultado de ``migrate_on_startup`` (para logs e testes)."""

    def __init__(self, applied: list[str], backup: Path | None, head: str) -> None:
        self.applied = applied
        self.backup = backup
        self.head = head


async def migrate_on_startup(engine: AsyncEngine, settings: Settings) -> MigrationResult:
    """Aplica ``upgrade head``; antes, com revisões pendentes num SQLite já usado, faz backup."""
    pending = await pending_revisions(engine)
    backup: Path | None = None
    db_path = settings.sqlite_path
    if pending and db_path is not None and db_path.exists():
        current = await current_revision(engine)
        if current is not None:
            backup = await asyncio.to_thread(
                backup_sqlite, db_path, settings.data_dir / "backup", settings.app_version
            )
            log.info("db.backup_created", path=backup.name, from_revision=current)
    if pending:
        await upgrade_engine(engine)
    return MigrationResult(pending, backup, script_head())
