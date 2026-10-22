"""Registro de routers (platform-foundation RF-03, D-33)."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import APIRouter

from simremap.api import registry
from simremap.api.main import create_app
from simremap.api.registry import (
    COMPONENT_ROUTER_MODULES,
    RouterPrefixError,
    RouterRegistryError,
    collect_routers,
    register,
    validate_router,
)
from simremap.api.static import IMMUTABLE_CACHE
from simremap.core.config import Settings
from simremap.core.errors import PROBLEM_JSON


@pytest.fixture
def clean_routers() -> Iterator[None]:
    saved = list(registry.ROUTERS)
    yield
    registry.ROUTERS[:] = saved


def _module(name: str, router: object, tag: str | None = None) -> types.ModuleType:
    module = types.ModuleType(name)
    module.router = router  # type: ignore[attr-defined]
    if tag is not None:
        module.TAG = tag  # type: ignore[attr-defined]
    return module


def test_static_module_list() -> None:
    assert COMPONENT_ROUTER_MODULES == (
        "simremap.api.health",
        "simremap.catalog.router",
        "simremap.dyno.router",
        "simremap.damage.router",
        "simremap.ecu.router",
        "simremap.profiles.router",
        "simremap.telemetry.router",
        "simremap.scenarios.router",
        "simremap.career.router",
        "simremap.ai.router",
    )


def test_collect_includes_health_and_skips_missing() -> None:
    tags = [tag for tag, _ in collect_routers()]
    assert "platform" in tags


async def test_t411_system_and_vehicle_routers_with_catalog_and_static(
    settings_factory: Any, static_dir: Path
) -> None:
    """T411: routers ``system`` (health/version) e ``vehicles`` registados, build estático e
    carga do catálogo no arranque, pela app completa."""
    tags = [tag for tag, _ in collect_routers()]
    assert tags[:2] == ["platform", "vehicle-catalog"]
    health, version, vehicles, spa = await _get(
        settings_factory(static_dir=static_dir),
        "/api/v1/health",
        "/api/v1/version",
        "/api/v1/vehicles",
        "/sessions/x/dyno",
    )
    assert health.status_code == version.status_code == vehicles.status_code == 200
    assert len(vehicles.json()["items"]) == 4
    assert spa.status_code == 200 and "SimuladorRemap" in spa.text


@pytest.mark.parametrize("prefix", ["/api", "/api/v2", "/v1", "/ws", "/api/v1x"])
def test_bad_prefix_rejected(prefix: str) -> None:
    router = APIRouter(prefix=prefix)

    @router.get("/x")
    async def handler() -> dict[str, str]:
        return {}

    with pytest.raises(RouterPrefixError):
        validate_router(router)


def test_route_without_prefix_outside_api_rejected() -> None:
    router = APIRouter()

    @router.get("/health")
    async def handler() -> dict[str, str]:
        return {}

    with pytest.raises(RouterPrefixError):
        validate_router(router)


def test_ws_prefix_accepted() -> None:
    router = APIRouter(prefix="/ws/v1")

    @router.websocket("/sessions/{session_id}/telemetry")
    async def ws(session_id: str) -> None:
        return None

    validate_router(router)


def test_collect_with_fake_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    good = APIRouter(prefix="/api/v1", tags=["fake"])

    @good.get("/fake")
    async def fake() -> dict[str, str]:
        return {"ok": "sim"}

    monkeypatch.setitem(sys.modules, "simremap_fake.router", _module("simremap_fake.router", good))
    entries = collect_routers(("simremap_fake.router", "simremap_absent.router"))
    assert [tag for tag, _ in entries] == ["fake"]


def test_module_without_router_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "simremap_norouter.router", _module("x", object()))
    with pytest.raises(RouterRegistryError, match="router"):
        collect_routers(("simremap_norouter.router",))


def test_bad_module_router_fails_create_app(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    bad = APIRouter(prefix="/legacy")

    @bad.get("/x")
    async def handler() -> dict[str, str]:
        return {}

    monkeypatch.setitem(sys.modules, "simremap.catalog.router", _module("c", bad, "catalog"))
    with pytest.raises(RouterPrefixError):
        create_app(settings)


def test_duplicate_tags_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    a = APIRouter(prefix="/api/v1")
    monkeypatch.setitem(sys.modules, "simremap_a.router", _module("a", a, "same"))
    monkeypatch.setitem(sys.modules, "simremap_b.router", _module("b", a, "same"))
    with pytest.raises(RouterRegistryError, match="duplicadas"):
        collect_routers(("simremap_a.router", "simremap_b.router"))


@pytest.mark.usefixtures("clean_routers")
def test_register_extra_router() -> None:
    router = APIRouter(prefix="/api/v1")
    register("extra", router)
    with pytest.raises(RouterRegistryError):
        register("extra", router)
    with pytest.raises(RouterPrefixError):
        register("other", APIRouter(prefix="/bad"))
    assert ("extra", router) in collect_routers(())


def test_nested_router_paths_validated() -> None:
    child = APIRouter(prefix="/child")

    @child.get("/c")
    async def c() -> dict[str, str]:
        return {}

    ok = APIRouter(prefix="/api/v1")
    ok.include_router(child, prefix="/inc")
    validate_router(ok)

    bad = APIRouter()
    bad.include_router(child)
    with pytest.raises(RouterPrefixError, match="/child/c"):
        validate_router(bad)


def test_route_without_path_rejected() -> None:
    from starlette.routing import BaseRoute

    router = APIRouter(prefix="/api/v1")
    router.routes.append(BaseRoute())
    with pytest.raises(RouterRegistryError, match="sem caminho"):
        validate_router(router)


# --------------------------------------------------------------------------- build estático (T237)


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>SimuladorRemap</title>", "utf-8")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)", "utf-8")
    (root / "favicon.svg").write_text("<svg/>", "utf-8")
    (tmp_path / "segredo.txt").write_text("não servir", "utf-8")
    return root


async def _get(settings: Settings, *paths: str, method: str = "GET") -> list[httpx.Response]:
    app = create_app(settings)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            return [await ac.request(method, p) for p in paths]


async def test_spa_fallback_and_assets(settings_factory: Any, static_dir: Path) -> None:
    root, spa, asset, fav, api404, ws404 = await _get(
        settings_factory(static_dir=static_dir),
        "/",
        "/dyno/qualquer",
        "/assets/index-abc123.js",
        "/favicon.svg",
        "/api/v1/inexistente",
        "/ws/v1/nada",
    )
    assert root.status_code == 200 and "SimuladorRemap" in root.text
    assert root.headers["cache-control"] == "no-cache"
    assert spa.status_code == 200 and spa.text == root.text
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == IMMUTABLE_CACHE
    assert fav.status_code == 200 and fav.text == "<svg/>"
    for resp in (api404, ws404):
        assert resp.status_code == 404
        assert resp.headers["content-type"] == PROBLEM_JSON
        assert resp.json()["code"] == "ROUTE_NOT_FOUND"


async def test_spa_does_not_escape_static_dir(settings_factory: Any, static_dir: Path) -> None:
    (resp,) = await _get(settings_factory(static_dir=static_dir), "/assets/../../segredo.txt")
    assert "não servir" not in resp.text


async def test_static_head_and_non_get(settings_factory: Any, static_dir: Path) -> None:
    settings = settings_factory(static_dir=static_dir)
    (head,) = await _get(settings, "/sessions/x/dyno", method="HEAD")
    assert head.status_code == 200 and head.content == b""
    (post,) = await _get(settings, "/sessions/x/dyno", method="POST")
    assert post.status_code == 404
    assert post.json()["code"] == "ROUTE_NOT_FOUND"


async def test_api_method_not_allowed_preserved_with_static(
    settings_factory: Any, static_dir: Path
) -> None:
    (resp,) = await _get(settings_factory(static_dir=static_dir), "/api/v1/health", method="POST")
    assert resp.status_code == 405
    assert resp.json()["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.parametrize("variant", ["none", "missing_dir", "no_index"])
async def test_static_not_built(
    settings_factory: Any,
    tmp_path: Path,
    variant: str,
    caplog: pytest.LogCaptureFixture,
    log_events: Any,
) -> None:
    caplog.set_level("WARNING")
    static: Path | None = None
    if variant == "missing_dir":
        static = tmp_path / "nao-existe"
    elif variant == "no_index":
        static = tmp_path / "vazio"
        static.mkdir()
    root, health = await _get(settings_factory(static_dir=static), "/", "/api/v1/health")
    assert root.status_code == 404
    assert root.headers["content-type"] == PROBLEM_JSON
    body = root.json()
    assert body["code"] == "STATIC_NOT_BUILT"
    assert "npm run build" in body["detail"]
    assert health.status_code == 200  # a API arranca normalmente
    assert "startup.static_missing" in [e["event"] for e in log_events(caplog)]


async def test_websocket_to_unknown_path_is_closed(settings_factory: Any) -> None:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    with TestClient(create_app(settings_factory())) as tc, pytest.raises(WebSocketDisconnect):
        with tc.websocket_connect("/ws/v1/nada") as ws:
            ws.receive_text()
