"""Fixtures partilhadas por todos os testes do backend (D-25, T021).

Fixtures disponíveis:
- ``settings``: ``Settings`` de teste (``env="test"``, ``worker_mode="thread"``, SQLite
  temporário em ``tmp_path``, sem Redis, sem build estático, migração automática ligada).
- ``settings_factory``: cria ``Settings`` de teste com overrides (``settings_factory(sim_hz=500)``).
- ``app``: ``create_app(settings)`` (lifespan ainda não iniciado).
- ``client``: ``httpx.AsyncClient`` sobre a app com lifespan ativo (banco migrado).
- ``db_session``: ``AsyncSession`` do ``sessionmaker`` da app (depende de ``client``).
- ``sync_client``: ``fastapi.testclient.TestClient`` com lifespan ativo (testes síncronos).
- ``log_events``: função que converte ``caplog.records`` em dicts de evento
  (``{"event": ..., "level": ..., <campos>}``) para loggers structlog e ``logging``.

Marcadores fora de ``make check`` (D-26): testes ``bench``, ``accuracy``, ``e2e`` e
``postgres`` só correm quando selecionados com ``-m`` (ex.: ``pytest -m bench``).
Testes em ``tests/e2e/`` recebem ``e2e`` e em ``tests/**/bench/`` recebem ``bench``
automaticamente.

Exemplo::

    async def test_lista(client: httpx.AsyncClient) -> None:
        resp = await client.get("/api/v1/vehicles")
        assert resp.status_code == 200
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from simremap.api.main import create_app
from simremap.core.config import Settings
from simremap.core.logging import configure_logging

SettingsFactory = Callable[..., Settings]
LogEvents = Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]]

_OPT_IN_MARKERS = ("bench", "accuracy", "e2e", "postgres")
_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Marca por diretório e salta os marcadores opt-in quando ``-m`` não os seleciona."""
    for item in items:
        parts = Path(str(item.path)).parts
        if "e2e" in parts:
            item.add_marker(pytest.mark.e2e)
        if "bench" in parts:
            item.add_marker(pytest.mark.bench)
    markexpr = str(config.getoption("markexpr") or "")
    for item in items:
        for marker in _OPT_IN_MARKERS:
            if item.get_closest_marker(marker) is not None and marker not in markexpr:
                item.add_marker(
                    pytest.mark.skip(reason=f"marcador {marker!r}: selecione com -m {marker}")
                )
                break


def _record_event(record: logging.LogRecord) -> dict[str, Any]:
    if isinstance(record.msg, dict):
        event = dict(record.msg)
    else:
        event = {"event": record.getMessage()}
        event.update(
            {k: v for k, v in record.__dict__.items() if k not in _RECORD_ATTRS and k[0] != "_"}
        )
    event.setdefault("level", record.levelname.lower())
    event.setdefault("logger", record.name)
    return event


@pytest.fixture(scope="session", autouse=True)
def _json_logging() -> None:
    """Logging JSON configurado como em produção (o lifespan reconfigura por app)."""
    configure_logging("INFO")


@pytest.fixture
def log_events() -> LogEvents:
    def collect(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
        return [_record_event(r) for r in caplog.records]

    return collect


def _test_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "data_dir": tmp_path,
        "static_dir": None,
        "database_url": f"sqlite+aiosqlite:///{tmp_path.as_posix()}/simremap-test.db",
        "db_auto_migrate": True,
        "redis_url": None,
        "worker_mode": "thread",
        "log_level": "WARNING",
        "cors_origins": ["http://localhost:5173", "http://127.0.0.1:5173"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings_factory(tmp_path: Path) -> SettingsFactory:
    def factory(**overrides: Any) -> Settings:
        return _test_settings(tmp_path, **overrides)

    return factory


@pytest.fixture
def settings(settings_factory: SettingsFactory) -> Settings:
    return settings_factory()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(app, startup_timeout=30, shutdown_timeout=30) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
async def db_session(app: FastAPI, client: httpx.AsyncClient) -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    async with maker() as session:
        yield session


@pytest.fixture
def sync_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as tc:
        yield tc
