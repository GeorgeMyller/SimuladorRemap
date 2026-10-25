"""Ambiente Alembic assíncrono do SimuladorRemap (platform-foundation RF-10, D-10).

Cadeia linear FIXA (``alembic heads`` deve devolver exatamente 1 revisão)::

    0001_foundation_base          platform-foundation      (down_revision = None)
    -> 0002_dyno_sessions_runs    dyno-bench
    -> 0003_damage_health_reports knock-and-failure-model
    -> 0004_ecu_calibrations      ecu-core
    -> 0005_profiles_session_state ecu-profiles
    -> 0006_telemetry_datalog     telemetry-datalogger
    -> 0007_scenarios_base        training-scenarios

Cada revisão tem ``down_revision`` igual à revisão da linha anterior
(ex.: ``0003_damage_health_reports`` → ``down_revision = "0002_dyno_sessions_runs"``).

Regras para quem escreve uma revisão:
- Arquivo ``versions/<revision>.py`` com ``revision = "<NNNN_componente_descricao>"`` e o
  ``down_revision`` acima. ATENÇÃO: o Alembic recusa carregar a cadeia inteira se a
  revisão anterior não existir no disco (todos os testes que usam migrações quebram).
  Só grave a sua revisão depois de a anterior existir.
- ``upgrade()`` e ``downgrade()`` completos; o ``downgrade`` remove só as tabelas da revisão.
- Use ``op.batch_alter_table`` para alterar tabelas (``render_as_batch=True`` em SQLite).
- Nenhuma migração insere dados (seeds correm no lifespan, data-model 6.3).
- Nomes de constraints vêm da ``NAMING_CONVENTION`` (``simremap.db.base``); passe
  ``sa.PrimaryKeyConstraint(..., name=op.f("pk_<tabela>"))`` etc.

Origem da URL (por ordem): ``config.attributes["database_url"]``, ``-x database_url=...``,
``Settings().db_url``. Uma ligação já aberta pode ser passada em
``config.attributes["connection"]`` (ligação síncrona, usada por ``run_sync``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from simremap.db.models import metadata

config = context.config
target_metadata = metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    if isinstance(url, str) and url:
        return url
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("database_url"):
        return x_args["database_url"]
    from simremap.core.config import Settings

    return Settings().db_url


def _configure(connection: Connection | None = None, **extra: Any) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
        **extra,
    )


def run_migrations_offline() -> None:
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def _ensure_sqlite_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)


async def _run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    _ensure_sqlite_dir(section["sqlalchemy.url"])
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if isinstance(connection, Connection):
        _do_run_migrations(connection)
        return
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
