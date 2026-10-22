"""Middlewares (T086, T236; RF-14, RF-16, RF-23, RF-24; D-32)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, FastAPI, Request, WebSocket
from fastapi.testclient import TestClient

from simremap.api.deps import body_limit, require_content_type
from simremap.api.main import create_app
from simremap.api.middleware import CSP_POLICY, SECURITY_HEADERS
from simremap.core.errors import PROBLEM_JSON

MiB = 1024 * 1024
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _probe_app(settings: Any) -> tuple[FastAPI, dict[str, int]]:
    app = create_app(settings)
    calls = {"upload": 0, "big": 0}

    @app.post("/api/v1/_probe/upload")
    async def upload(request: Request) -> dict[str, int]:
        calls["upload"] += 1
        return {"size": len(await request.body())}

    @app.post("/api/v1/_probe/json")
    async def json_body(payload: dict[str, Any]) -> dict[str, int]:
        calls["upload"] += 1
        return {"keys": len(payload)}

    @app.post("/api/v1/_probe/big", dependencies=[body_limit(4096)])
    async def big(request: Request) -> dict[str, int]:
        calls["big"] += 1
        return {"size": len(await request.body())}

    @app.post("/api/v1/_probe/strict", dependencies=[require_content_type("application/json")])
    async def strict() -> dict[str, bool]:
        return {"ok": True}

    component = APIRouter(prefix="/api/v1/_probe/component")

    @component.post("/raw")
    async def raw(request: Request) -> dict[str, int]:
        calls["upload"] += 1
        return {"size": len(await request.body())}

    app.include_router(component)
    return app, calls


@pytest.fixture
async def probe(settings_factory: Any) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, int]]]:
    app, calls = _probe_app(settings_factory(max_body_bytes=1024))
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            yield ac, calls


# --------------------------------------------------------------------------- X-Request-ID


@pytest.mark.parametrize(
    ("sent", "echoed"),
    [("abc-123", True), ("A" * 64, True), ("A" * 65, False), ("x y", False), ("abc$", False)],
)
async def test_request_id_rules(client: httpx.AsyncClient, sent: str, echoed: bool) -> None:
    resp = await client.get("/api/v1/health", headers={"X-Request-ID": sent})
    rid = resp.headers["x-request-id"]
    if echoed:
        assert rid == sent
    else:
        assert UUID4.fullmatch(rid)


async def test_request_id_generated_and_in_problem_body(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/nada")
    rid = resp.headers["x-request-id"]
    assert UUID4.fullmatch(rid)
    assert resp.json()["request_id"] == rid


# --------------------------------------------------------------------------- CORS


async def test_cors_allows_only_local_origins(client: httpx.AsyncClient) -> None:
    preflight = {"Access-Control-Request-Method": "POST"}
    ok = await client.options(
        "/api/v1/health", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in ok.headers
    evil = await client.options(
        "/api/v1/health", headers={"Origin": "http://evil.example", **preflight}
    )
    assert "access-control-allow-origin" not in evil.headers
    simple = await client.get("/api/v1/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert simple.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "x-request-id" in simple.headers["access-control-expose-headers"].lower()
    other = await client.get("/api/v1/health", headers={"Origin": "http://localhost:9999"})
    assert "access-control-allow-origin" not in other.headers


# --------------------------------------------------------------------------- cabeçalhos


@pytest.mark.parametrize("path", ["/", "/api/v1/health", "/api/v1/nao-existe"])
async def test_security_headers_everywhere(client: httpx.AsyncClient, path: str) -> None:
    resp = await client.get(path)
    for name, value in SECURITY_HEADERS.items():
        assert resp.headers[name] == value
    assert "connect-src 'self' ws://localhost:* ws://127.0.0.1:*" in CSP_POLICY
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-frame-options"] == "DENY"


async def test_security_headers_on_500(settings_factory: Any) -> None:
    app = create_app(settings_factory())

    @app.get("/api/v1/_probe/boom")
    async def boom() -> None:
        raise RuntimeError("x")

    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            resp = await ac.get("/api/v1/_probe/boom")
    assert resp.status_code == 500
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["content-security-policy"] == CSP_POLICY


async def test_docs_have_relaxed_csp_only_in_dev_test(client: httpx.AsyncClient) -> None:
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert "cdn.jsdelivr.net" in resp.headers["content-security-policy"]


async def test_docs_disabled_in_prod(settings_factory: Any) -> None:
    app = create_app(settings_factory(env="prod"))
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            docs = await ac.get("/docs")
            spec = await ac.get("/openapi.json")
    assert docs.status_code == 404
    assert spec.status_code == 200


# --------------------------------------------------------------------------- limite de corpo


async def test_body_over_limit_rejected_before_handler(
    probe: tuple[httpx.AsyncClient, dict[str, int]],
) -> None:
    ac, calls = probe
    resp = await ac.post("/api/v1/_probe/upload", content=b"x" * 2000)
    assert resp.status_code == 413
    assert resp.headers["content-type"] == PROBLEM_JSON
    body = resp.json()
    assert body["code"] == "PAYLOAD_TOO_LARGE"
    assert body["type"] == "urn:simremap:problem:payload-too-large"
    assert resp.headers["x-frame-options"] == "DENY"
    assert calls["upload"] == 0
    ok = await ac.post("/api/v1/_probe/upload", content=b"x" * 1000)
    assert ok.json() == {"size": 1000}


async def test_included_router_raw_body_rejected_before_handler(
    probe: tuple[httpx.AsyncClient, dict[str, int]],
) -> None:
    ac, calls = probe
    resp = await ac.post("/api/v1/_probe/component/raw", content=b"x" * 2000)
    assert resp.status_code == 413
    assert calls["upload"] == 0


async def test_route_override_accepts_more(
    probe: tuple[httpx.AsyncClient, dict[str, int]],
) -> None:
    ac, calls = probe
    resp = await ac.post("/api/v1/_probe/big", content=b"x" * 3000)
    assert resp.status_code == 200
    assert resp.json() == {"size": 3000}
    too_big = await ac.post("/api/v1/_probe/big", content=b"x" * 5000)
    assert too_big.status_code == 413
    assert "4096" in too_big.json()["detail"]
    assert calls["big"] == 1


async def test_json_route_over_limit_is_413(
    probe: tuple[httpx.AsyncClient, dict[str, int]],
) -> None:
    ac, calls = probe
    resp = await ac.post("/api/v1/_probe/json", json={"k": "x" * 2000})
    assert resp.status_code == 413
    assert calls["upload"] == 0


async def test_chunked_body_counted_while_streaming(
    probe: tuple[httpx.AsyncClient, dict[str, int]],
) -> None:
    ac, _ = probe

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"y" * 400

    resp = await ac.post("/api/v1/_probe/upload", content=chunks())
    assert resp.status_code == 413
    assert resp.json()["code"] == "PAYLOAD_TOO_LARGE"


async def test_default_limit_is_16_mib(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/health", content=b"x" * (17 * MiB))
    assert resp.status_code == 413
    assert resp.json()["code"] == "PAYLOAD_TOO_LARGE"


async def test_unknown_or_wrong_method_route_uses_global_limit(
    client: httpx.AsyncClient,
) -> None:
    """Sem rota completa (404/405) vale o limite global, mesmo com rotas de 64 MiB."""
    for path in ("/api/v1/nada", "/api/v1/vehicles"):
        resp = await client.post(path, content=b"x" * (17 * MiB))
        assert resp.status_code == 413, path
        assert "16777216" in resp.json()["detail"]


async def test_route_limit_64_mib_on_log_import(client: httpx.AsyncClient) -> None:
    """E-28 (``body_limit(64 MiB)``): 17 MiB passa o middleware e chega à validação."""
    resp = await client.post(
        "/api/v1/logs/import",
        content=b"x" * (17 * MiB),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code != 413
    too_big = await client.post(
        "/api/v1/logs/import",
        content=b"x" * (65 * MiB),
        headers={"Content-Type": "application/json"},
    )
    assert too_big.status_code == 413
    assert str(64 * MiB) in too_big.json()["detail"]


def test_global_dependency_does_not_break_websocket_routes(settings_factory: Any) -> None:
    """``enforce_declared_body_limit`` aceita ``HTTPConnection`` e ignora WebSocket."""
    app = create_app(settings_factory())
    ws_router = APIRouter(prefix="/ws/v1")

    @ws_router.websocket("/_probe")
    async def probe_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"ok": True})
        await websocket.close()

    app.include_router(ws_router)
    with TestClient(app) as tc, tc.websocket_connect("/ws/v1/_probe") as ws:
        assert ws.receive_json() == {"ok": True}


def test_body_limit_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="positivo"):
        body_limit(0)


# --------------------------------------------------------------------------- 415


async def test_unsupported_media_type(probe: tuple[httpx.AsyncClient, dict[str, int]]) -> None:
    ac, _ = probe
    resp = await ac.post(
        "/api/v1/_probe/strict", content=b"a=1", headers={"Content-Type": "text/plain"}
    )
    assert resp.status_code == 415
    assert resp.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"
    ok = await ac.post("/api/v1/_probe/strict", json={})
    assert ok.status_code == 200
