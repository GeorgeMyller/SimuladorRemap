"""``ProblemDetail`` em todas as respostas de erro (T077; RF-05; D-13)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from simremap.api.deps import require_content_type
from simremap.api.main import create_app
from simremap.core.config import Settings
from simremap.core.errors import PROBLEM_JSON, ProblemDetail


class _Body(BaseModel):
    rpm: int


def _app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.post("/api/v1/_probe/body")
    async def body(payload: _Body) -> dict[str, int]:
        return {"rpm": payload.rpm}

    @app.post("/api/v1/_probe/json", dependencies=[require_content_type("application/json")])
    async def json_only(request: Request) -> dict[str, int]:
        return {"n": len(await request.body())}

    @app.get("/api/v1/_probe/boom")
    async def boom() -> None:
        raise RuntimeError("/srv/app/segredo.py: senha=123")

    return app


@pytest.fixture
def tc(settings_factory: object) -> Iterator[TestClient]:
    settings = settings_factory(max_body_bytes=1024)  # type: ignore[operator]
    with TestClient(_app(settings), raise_server_exceptions=False) as client:
        yield client


CASES = [
    ("GET", "/api/v1/nao-existe", {}, 404, "ROUTE_NOT_FOUND"),
    ("DELETE", "/api/v1/health", {}, 405, "METHOD_NOT_ALLOWED"),
    ("POST", "/api/v1/_probe/body", {"content": b"x" * 2048}, 413, "PAYLOAD_TOO_LARGE"),
    (
        "POST",
        "/api/v1/_probe/json",
        {"content": b"a", "headers": {"Content-Type": "text/plain"}},
        415,
        "UNSUPPORTED_MEDIA_TYPE",
    ),
    ("POST", "/api/v1/_probe/body", {"json": {"rpm": "alto"}}, 422, "VALIDATION_FAILED"),
    ("GET", "/api/v1/_probe/boom", {}, 500, "INTERNAL_ERROR"),
]


@pytest.mark.parametrize(("method", "path", "kwargs", "status", "code"), CASES)
def test_error_is_problem_json(  # noqa: PLR0917 - parâmetros do parametrize
    tc: TestClient, method: str, path: str, kwargs: dict[str, object], status: int, code: str
) -> None:
    options = dict(kwargs)
    headers = {"X-Request-ID": f"rid-{status}", **dict(options.pop("headers", {}))}  # type: ignore[call-overload]
    resp = tc.request(method, path, headers=headers, **options)  # type: ignore[arg-type]
    assert resp.headers["x-request-id"] == f"rid-{status}"
    assert resp.status_code == status
    assert resp.headers["content-type"] == PROBLEM_JSON
    problem = ProblemDetail.model_validate(resp.json())
    assert problem.status == status
    assert problem.code == code
    assert problem.type == "urn:simremap:problem:" + code.lower().replace("_", "-")
    assert problem.request_id == resp.headers["x-request-id"]
    assert problem.instance == path
    assert problem.title and problem.detail
    if status == 422:
        assert problem.errors and problem.errors[0].loc == ["body", "rpm"]
    else:
        assert problem.errors is None


def test_500_has_no_stack_trace_or_paths(tc: TestClient) -> None:
    resp = tc.get("/api/v1/_probe/boom")
    text = resp.text
    for leak in ("Traceback", "segredo", "/srv/app", "senha", "RuntimeError", ".py"):
        assert leak not in text


def test_problem_schema_published_in_openapi(tc: TestClient) -> None:
    spec = tc.get("/openapi.json").json()
    schema = spec["components"]["schemas"]["ProblemDetail"]
    assert set(schema["required"]) == {"type", "title", "status", "detail", "code", "request_id"}
