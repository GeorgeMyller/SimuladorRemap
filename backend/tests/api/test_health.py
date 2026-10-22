"""Health, versão e formato problem+json da app mínima (RF-05, RF-07, RF-08, RF-14)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from simremap.api.main import create_app
from simremap.core.config import Settings
from simremap.core.errors import PROBLEM_JSON, ProblemDetail, catalog_sha256
from simremap.db.migrate import script_head


async def test_health_ok_with_redis_disabled(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"database", "redis", "sim_worker"}
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "disabled"
    assert body["checks"]["sim_worker"]["status"] == "ok"
    assert body["active_sessions"] == 0
    assert body["uptime_s"] >= 0


async def test_health_degraded_when_redis_down(settings_factory: object) -> None:
    from asgi_lifespan import LifespanManager

    settings = settings_factory(redis_url="redis://127.0.0.1:1/0")  # type: ignore[operator]
    app = create_app(settings)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            resp = await ac.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["checks"]["redis"]["status"] == "down"


async def test_health_down_when_database_gone(app: FastAPI, client: httpx.AsyncClient) -> None:
    await app.state.engine.dispose()
    app.state.engine = None
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 503
    assert resp.headers["content-type"] == PROBLEM_JSON
    body = resp.json()
    assert body["code"] == "SERVICE_UNAVAILABLE"
    assert body["checks"]["database"]["status"] == "down"


async def test_version(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "v1"
    assert body["ws_envelope_version"] == 1
    assert body["package_format_version"] == 1
    assert body["datalog_format_version"] == 1
    assert body["alembic_head"] == script_head()
    assert body["error_catalog_sha256"] == catalog_sha256()
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?", body["app_version"])
    assert body["python_version"].startswith("3.")


async def test_version_announces_native_extension(client: httpx.AsyncClient) -> None:
    """T031: ``native_enabled``/``native_version`` seguem o seletor ``simremap.core.native``."""
    from simremap.core.native import native_enabled, native_version

    body = (await client.get("/api/v1/version")).json()
    assert body["native_enabled"] is native_enabled()
    assert body["native_version"] == native_version()
    assert (body["native_version"] is not None) is body["native_enabled"]


async def test_request_id_echo_and_regeneration(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"
    resp = await client.get("/api/v1/health", headers={"X-Request-ID": "x" * 200})
    assert re.fullmatch(r"[0-9a-f-]{36}", resp.headers["x-request-id"])


async def test_unknown_api_route_is_problem_json(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/inexistente", headers={"X-Request-ID": "rid-1"})
    assert resp.status_code == 404
    assert resp.headers["content-type"] == PROBLEM_JSON
    problem = ProblemDetail.model_validate(resp.json())
    assert problem.code == "ROUTE_NOT_FOUND"
    assert problem.type == "urn:simremap:problem:route-not-found"
    assert problem.request_id == "rid-1"
    assert problem.instance == "/api/v1/inexistente"


async def test_method_not_allowed(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/health")
    assert resp.status_code == 405
    assert resp.json()["code"] == "METHOD_NOT_ALLOWED"
    assert resp.headers["content-type"] == PROBLEM_JSON


class _Body(BaseModel):
    rpm: int


def _app_with_probe_routes(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.post("/api/v1/_probe/validate")
    async def validate(body: _Body) -> dict[str, int]:
        return {"rpm": body.rpm}

    @app.get("/api/v1/_probe/boom")
    async def boom() -> None:
        raise RuntimeError("/segredo/caminho/interno.py falhou")

    return app


def test_validation_failed_has_errors(settings: Settings) -> None:
    with TestClient(_app_with_probe_routes(settings)) as tc:
        resp = tc.post("/api/v1/_probe/validate", json={"rpm": "muito"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["errors"][0]["loc"] == ["body", "rpm"]
    assert resp.headers["content-type"] == PROBLEM_JSON


def test_internal_error_hides_details(
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
    log_events: Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]],
) -> None:
    with TestClient(_app_with_probe_routes(settings)) as tc:
        resp = tc.get("/api/v1/_probe/boom", headers={"X-Request-ID": "boom-1"})
    assert resp.status_code == 500
    assert resp.headers["content-type"] == PROBLEM_JSON
    assert resp.headers["x-request-id"] == "boom-1"
    body = resp.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["request_id"] == "boom-1"
    assert "segredo" not in resp.text
    assert "Traceback" not in resp.text
    events = [e for e in log_events(caplog) if e["event"] == "http.unhandled_exception"]
    assert len(events) == 1
    assert events[0]["request_id"] == "boom-1"


def test_openapi_lists_platform_tag(sync_client: TestClient) -> None:
    spec = sync_client.get("/openapi.json").json()
    platform = next(t for t in spec["tags"] if t["name"] == "platform")
    assert "Fundação" in platform["description"]
    assert spec["info"]["version"] == "v1"
    assert all(p.startswith(("/api/v1/", "/ws/v1/")) for p in spec["paths"])


class _FakeHost:
    """Host mínimo com a interface usada pelo health (``health()`` e ``active_sessions``)."""

    def __init__(self, status: str, active: int) -> None:
        self.status = status
        self.active_sessions = active

    def health(self) -> dict[str, object]:
        return {"status": self.status, "detail": f"{self.active_sessions} sessões"}


async def test_health_degraded_when_sim_worker_down(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    real = app.state.worker_host
    app.state.worker_host = _FakeHost("down", 1)
    try:
        resp = await client.get("/api/v1/health")
    finally:
        app.state.worker_host = real
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["sim_worker"]["status"] == "down"
    assert body["active_sessions"] == 1


async def test_health_counts_real_worker_sessions(app: FastAPI, client: httpx.AsyncClient) -> None:
    host = app.state.worker_host
    await host.start_session("s-health", "simremap.core.worker.synthetic:SyntheticTask", b"")
    try:
        body = (await client.get("/api/v1/health")).json()
    finally:
        await host.stop_session("s-health")
    assert body["status"] == "ok"
    assert body["active_sessions"] == 1
    assert body["checks"]["sim_worker"]["status"] == "ok"


async def test_health_without_worker_host_reports_ok(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    real = app.state.worker_host
    del app.state.worker_host
    try:
        body = (await client.get("/api/v1/health")).json()
    finally:
        app.state.worker_host = real
    assert body["checks"]["sim_worker"]["status"] == "ok"
    assert body["checks"]["sim_worker"]["detail"] == "0 sessões ativas"


class _OkCache:
    backend = "redis"

    async def check(self) -> tuple[str, float, None]:
        return ("ok", 0.4, None)


async def test_health_redis_ok_through_cache(settings_factory: Any) -> None:
    from asgi_lifespan import LifespanManager

    app = create_app(settings_factory(redis_url="redis://127.0.0.1:1/0"))
    async with LifespanManager(app) as manager:
        real = app.state.cache
        app.state.cache = _OkCache()
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            body = (await ac.get("/api/v1/health")).json()
        app.state.cache = real
    assert body["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"
    assert body["checks"]["redis"]["latency_ms"] == 0.4


async def test_health_latency_p95_under_50ms(client: httpx.AsyncClient) -> None:
    import time

    samples = []
    for _ in range(40):
        t0 = time.perf_counter()
        resp = await client.get("/api/v1/health")
        samples.append((time.perf_counter() - t0) * 1000)
        assert resp.status_code == 200
    samples.sort()
    assert samples[int(0.95 * len(samples)) - 1] < 50
