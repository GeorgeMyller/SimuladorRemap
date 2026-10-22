"""``create_app`` e lifespan (T239, T407, T448, T449; RF-02, EC-01, EC-08, EC-12)."""

from __future__ import annotations

import asyncio
import importlib
import threading
import time
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from simremap.api import main
from simremap.api.main import StartupError, connect_with_retry, create_app
from simremap.core.cache import MemoryCache
from simremap.core.worker.host import SimWorkerHost
from simremap.db.engine import build_engine

STARTUP_ORDER = [
    "startup.settings",
    "startup.database",
    "startup.migrations",
    "startup.seeds",
    "startup.cache",
    "startup.catalog",
    "startup.worker_host",
    "startup.routers",
    "startup.complete",
]
SHUTDOWN_ORDER = ["shutdown.worker_host", "shutdown.cache", "shutdown.database"]
TASK = "simremap.core.worker.synthetic:SyntheticTask"


async def test_lifespan_order_and_clean_shutdown(
    settings_factory: Any, caplog: pytest.LogCaptureFixture, log_events: Any
) -> None:
    app = create_app(settings_factory(log_level="INFO"))
    caplog.set_level("INFO")
    async with LifespanManager(app):
        assert isinstance(app.state.cache, MemoryCache)
        host = app.state.worker_host
        assert isinstance(host, SimWorkerHost) and host.running
        assert host.active_sessions == 0  # 0 workers até à primeira sessão
        await host.start_session("s1", TASK, b"")
        assert any(t.name == "simworker-s1" for t in threading.enumerate())
        t0 = time.monotonic()
    assert time.monotonic() - t0 < 10  # EC-12: shutdown com sessão ativa em ≤ 10 s
    events = [e["event"] for e in log_events(caplog)]
    startup = [e for e in events if e in STARTUP_ORDER]
    shutdown = [e for e in events if e in SHUTDOWN_ORDER]
    assert startup == STARTUP_ORDER
    assert shutdown == SHUTDOWN_ORDER
    assert events.index("worker.stopped") < events.index("shutdown.worker_host")
    await asyncio.sleep(0.2)
    assert [t.name for t in threading.enumerate() if t.name.startswith("simworker")] == []
    assert not host.running


async def test_process_mode_shutdown_leaves_no_children(settings_factory: Any) -> None:
    import multiprocessing

    app = create_app(settings_factory(worker_mode="process"))
    async with LifespanManager(app, startup_timeout=30, shutdown_timeout=30):
        handle = await app.state.worker_host.start_session("p1", TASK, b"")
        assert handle.mode == "process"
        assert len(multiprocessing.active_children()) == 1
    assert multiprocessing.active_children() == []


async def test_seeds_idempotent_across_boots(settings_factory: Any) -> None:
    settings = settings_factory(app_version="0.1.0")
    first = create_app(settings)
    async with LifespanManager(first):
        install_id = first.state.install_id
    second = create_app(settings_factory(app_version="0.2.0"))
    async with LifespanManager(second):
        assert second.state.install_id == install_id
        from simremap.db.models.foundation import AppMeta

        async with second.state.sessionmaker() as session:
            boot = await session.get(AppMeta, "last_boot_app_version")
            created = await session.get(AppMeta, "schema_created_at")
    assert boot is not None and boot.value == "0.2.0"
    assert created is not None and created.value.endswith("+00:00")


async def test_without_auto_migrate_seeds_are_skipped(
    settings_factory: Any, caplog: pytest.LogCaptureFixture, log_events: Any
) -> None:
    app = create_app(settings_factory(db_auto_migrate=False, log_level="INFO"))
    caplog.set_level("INFO")
    async with LifespanManager(app):
        assert app.state.install_id is None
    assert "startup.seeds_skipped" in [e["event"] for e in log_events(caplog)]


async def test_database_unavailable_exits_with_code_3(
    settings_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    log_events: Any,
) -> None:
    monkeypatch.setattr(main, "DB_RETRY_DELAYS_S", (0.0,))
    app = create_app(
        settings_factory(database_url="postgresql+asyncpg://u:p@127.0.0.1:1/nada", log_level="INFO")
    )
    caplog.set_level("INFO")
    with pytest.raises(StartupError) as info:
        async with LifespanManager(app, startup_timeout=30):
            pass  # pragma: no cover - o arranque falha antes
    assert info.value.exit_code == 3
    assert info.value.code == "DATABASE_UNAVAILABLE"
    events = log_events(caplog)
    retries = [e for e in events if e["event"] == "startup.database_retry"]
    assert [r["attempt"] for r in retries] == [1, 2, 3, 4, 5]
    failed = next(e for e in events if e["event"] == "startup.failed")
    assert failed["code"] == "DATABASE_UNAVAILABLE"
    assert failed["exit_code"] == 3


async def test_lifespan_loads_catalog_into_app_state(
    settings_factory: Any, caplog: pytest.LogCaptureFixture, log_events: Any
) -> None:
    """T411: ``startup.catalog`` entre ``cache`` e ``worker_host``; ``app.state.catalog``."""
    from simremap.catalog.service import CatalogService, get_catalog

    app = create_app(settings_factory(log_level="INFO", catalog_allow_drafts=False))
    caplog.set_level("INFO")
    async with LifespanManager(app, startup_timeout=30):
        catalog = app.state.catalog
        assert isinstance(catalog, CatalogService)
        assert get_catalog() is catalog
        assert catalog.allow_drafts is False  # SIMREMAP_CATALOG_ALLOW_DRAFTS explícito
        assert len(catalog.vehicle_ids) == 4
    event = next(e for e in log_events(caplog) if e["event"] == "startup.catalog")
    assert event["vehicles"] == 4 and len(event["catalog_sha256"]) == 64


async def test_invalid_catalog_aborts_startup_with_exit_4(
    settings_factory: Any,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
    log_events: Any,
) -> None:
    """``CATALOG_INVALID``: ``StartupError`` com saída 4, sem worker host nem routers."""
    empty = tmp_path / "catalogo-vazio"
    empty.mkdir()
    app = create_app(settings_factory(log_level="INFO", catalog_dir=empty))
    caplog.set_level("INFO")
    with pytest.raises(StartupError) as info:
        async with LifespanManager(app, startup_timeout=30):
            pass  # pragma: no cover - o arranque falha antes
    assert (info.value.code, info.value.exit_code) == ("CATALOG_INVALID", 4)
    assert main.last_startup_exit_code() == 4
    events = log_events(caplog)
    failed = next(e for e in events if e["event"] == "startup.failed")
    assert failed["code"] == "CATALOG_INVALID"
    assert failed["issues"][0]["file"] == "manifest.json"
    names = [e["event"] for e in events]
    assert "startup.worker_host" not in names and "startup.complete" not in names


async def test_connect_with_retry_backoff_schedule(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    calls = {"n": 0}

    async def flaky_probe(_engine: Any) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("ainda não")

    monkeypatch.setattr(main, "_probe_database", flaky_probe)
    engine = build_engine(settings_factory())
    try:
        assert await connect_with_retry(engine, 5, sleep=fake_sleep) == 3
        assert waits == [0.5, 1.0]
        calls["n"] = -10
        waits.clear()
        with pytest.raises(StartupError):
            await connect_with_retry(engine, 5, sleep=fake_sleep)
        assert waits == [0.5, 1.0, 2.0, 4.0]
    finally:
        await engine.dispose()


def test_invalid_settings_exit_code_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from simremap.core.config import get_settings

    monkeypatch.setenv("SIMREMAP_SIM_HZ", "2000")
    get_settings.cache_clear()
    module = importlib.reload(main)
    try:
        with pytest.raises(SystemExit) as info:
            _ = module.app
        assert info.value.code == 2
        assert "startup.invalid_settings" in capsys.readouterr().out
    finally:
        get_settings.cache_clear()
        monkeypatch.delenv("SIMREMAP_SIM_HZ")
        importlib.reload(main)


def test_default_app_is_created_lazily(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from simremap.core.config import get_settings

    monkeypatch.setenv("SIMREMAP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SIMREMAP_STATIC_DIR", str(tmp_path / "static"))
    get_settings.cache_clear()
    module = importlib.reload(main)
    try:
        assert module.app is module.app
        assert module.app.state.settings.data_dir == tmp_path
        with pytest.raises(AttributeError):
            _ = module.nao_existe
    finally:
        get_settings.cache_clear()
        importlib.reload(main)


def test_openapi_metadata(sync_client: Any) -> None:
    spec = sync_client.get("/openapi.json").json()
    assert spec["info"]["title"] == "SimuladorRemap API"
    assert spec["info"]["version"] == "v1"
    assert "/api/v1/" in spec["info"]["description"]
    assert spec["tags"][0]["name"] == "platform"
    assert all(path.startswith(("/api/v1/", "/ws/v1/")) for path in spec["paths"])


async def test_bind_public_warns(
    settings_factory: Any, caplog: pytest.LogCaptureFixture, log_events: Any
) -> None:
    app = create_app(settings_factory(bind_public=True, log_level="INFO"))
    caplog.set_level("INFO")
    async with LifespanManager(app):
        pass
    assert "startup.bind_public" in [e["event"] for e in log_events(caplog)]


async def test_startup_failure_after_database_cleans_up(
    settings_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_cache(_settings: Any) -> Any:
        raise RuntimeError("cache quebrado")

    monkeypatch.setattr(main, "build_cache", broken_cache)
    app = create_app(settings_factory())
    with pytest.raises(RuntimeError, match="cache quebrado"):
        async with LifespanManager(app):
            pass  # pragma: no cover

    async def broken_start(self: SimWorkerHost) -> None:
        raise RuntimeError("host quebrado")

    monkeypatch.setattr(main, "build_cache", lambda s: MemoryCache())
    monkeypatch.setattr(SimWorkerHost, "start", broken_start)
    app = create_app(settings_factory())
    with pytest.raises(RuntimeError, match="host quebrado"):
        async with LifespanManager(app):
            pass  # pragma: no cover


async def test_health_through_real_lifespan(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/health")).json()
    assert body["checks"]["sim_worker"]["detail"] == "0 sessões ativas (thread)"
