"""Dependência ``get_session`` e engine em memória (RF-09, base para T087)."""

from __future__ import annotations

import httpx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlmodel import select

from simremap.api.deps import SessionDep, SettingsDep
from simremap.api.main import create_app
from simremap.core.config import Settings
from simremap.db.models.foundation import APP_META_KEYS, AppMeta


def _probe_app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.post("/api/v1/_probe/meta/{key}")
    async def write(key: str, session: SessionDep, fail: bool = False) -> dict[str, str]:
        session.add(AppMeta(key=key, value="v"))
        await session.flush()
        if fail:
            raise RuntimeError("falha depois do add")
        await session.commit()
        return {"key": key}

    @app.get("/api/v1/_probe/meta")
    async def read(session: SessionDep, cfg: SettingsDep) -> dict[str, object]:
        rows = (await session.execute(select(AppMeta))).scalars().all()
        keys = [r.key for r in rows if r.key not in APP_META_KEYS]
        return {"keys": keys, "env": cfg.env}

    return app


async def _run(app: FastAPI) -> tuple[httpx.Response, httpx.Response, httpx.Response]:
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            ok = await ac.post("/api/v1/_probe/meta/a")
            failed = await ac.post("/api/v1/_probe/meta/b", params={"fail": "true"})
            listed = await ac.get("/api/v1/_probe/meta")
    return ok, failed, listed


async def test_rollback_on_exception(settings: Settings) -> None:
    ok, failed, listed = await _run(_probe_app(settings))
    assert ok.status_code == 200
    assert failed.status_code == 500
    assert listed.json() == {"keys": ["a"], "env": "test"}


async def test_in_memory_sqlite_with_static_pool(settings_factory: object) -> None:
    settings = settings_factory(database_url="sqlite+aiosqlite:///:memory:")  # type: ignore[operator]
    ok, failed, listed = await _run(_probe_app(settings))
    assert ok.status_code == 200
    assert failed.status_code == 500
    assert listed.json()["keys"] == ["a"]


async def test_auto_migrate_disabled(settings_factory: object) -> None:
    settings = settings_factory(db_auto_migrate=False)  # type: ignore[operator]
    app = create_app(settings)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            resp = await ac.get("/api/v1/health")
    assert resp.status_code == 200
