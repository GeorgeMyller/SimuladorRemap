"""Catálogo de erros e ProblemDetail (platform-foundation RF-05, RF-06)."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from simremap.core import errors
from simremap.core.errors import (
    COMPONENT_ERROR_MODULES,
    FOUNDATION_CODES,
    RETIRED_CODES,
    ErrorCodeConflict,
    ErrorCodeInvalid,
    ProblemDetail,
    SimRemapError,
    catalog,
    catalog_sha256,
    get_error,
    load_component_errors,
    problem_type,
    register_error,
)


@pytest.fixture
def clean_catalog() -> Iterator[None]:
    """Restaura o catálogo global depois do teste."""
    snapshot = dict(errors._CATALOG)
    yield
    errors._CATALOG.clear()
    errors._CATALOG.update(snapshot)


def test_foundation_codes_registered_with_fixed_status() -> None:
    expected = {
        "VALIDATION_FAILED": 422,
        "ROUTE_NOT_FOUND": 404,
        "RESOURCE_NOT_FOUND": 404,
        "METHOD_NOT_ALLOWED": 405,
        "PAYLOAD_TOO_LARGE": 413,
        "UNSUPPORTED_MEDIA_TYPE": 415,
        "CONFLICT": 409,
        "INTERNAL_ERROR": 500,
        "SERVICE_UNAVAILABLE": 503,
        "DATABASE_UNAVAILABLE": 503,
        "SIM_WORKER_UNAVAILABLE": 503,
        "SIM_WORKER_BUSY": 503,
        "SIM_CAPACITY_EXCEEDED": 409,
        "STORAGE_FULL": 507,
        "STATIC_NOT_BUILT": 404,
    }
    assert set(expected) == set(FOUNDATION_CODES)
    for code, status in expected.items():
        assert get_error(code).status == status


def test_retired_codes_absent() -> None:
    assert RETIRED_CODES.isdisjoint(catalog())


def test_problem_type_rule() -> None:
    assert problem_type("VEHICLE_NOT_FOUND") == "urn:simremap:problem:vehicle-not-found"
    assert get_error("SIM_WORKER_BUSY").type == "urn:simremap:problem:sim-worker-busy"


@pytest.mark.usefixtures("clean_catalog")
def test_register_same_status_is_idempotent() -> None:
    first = register_error("TEST_IDEMPOTENT", 404, "Teste")
    again = register_error("TEST_IDEMPOTENT", 404, "Outro título")
    assert first is again


@pytest.mark.usefixtures("clean_catalog")
def test_register_conflicting_status_raises() -> None:
    register_error("TEST_CONFLICT", 404, "Teste")
    with pytest.raises(ErrorCodeConflict):
        register_error("TEST_CONFLICT", 409, "Teste")


@pytest.mark.parametrize(
    ("code", "status", "title"),
    [
        ("lowercase", 400, "x"),
        ("AB", 400, "x"),
        ("A" * 65, 400, "x"),
        ("VALID_CODE", 399, "x"),
        ("VALID_CODE", 600, "x"),
        ("VALID_CODE", 400, ""),
        ("VALID_CODE", 400, "t" * 121),
        ("VALIDATION_ERROR", 422, "aposentado"),
    ],
)
@pytest.mark.usefixtures("clean_catalog")
def test_register_invalid(code: str, status: int, title: str) -> None:
    with pytest.raises(ErrorCodeInvalid):
        register_error(code, status, title)


@pytest.mark.usefixtures("clean_catalog")
def test_catalog_sha256_stable_and_sensitive() -> None:
    before = catalog_sha256()
    assert before == catalog_sha256()
    assert len(before) == 64
    register_error("TEST_SHA_CHANGE", 400, "Teste")
    assert catalog_sha256() != before


@pytest.mark.usefixtures("clean_catalog")
def test_subclass_auto_registers_and_builds_problem() -> None:
    class SessionGone(SimRemapError):
        code = "TEST_SESSION_GONE"
        status = 404
        title = "Sessão não encontrada"

    assert get_error("TEST_SESSION_GONE").status == 404
    exc = SessionGone("A sessão abc não existe.", session_id="abc", headers={"Retry-After": "1"})
    problem = exc.to_problem("req-1", "/api/v1/sessions/abc")
    assert problem.status == 404
    assert problem.code == "TEST_SESSION_GONE"
    assert problem.type == "urn:simremap:problem:test-session-gone"
    assert problem.model_dump()["session_id"] == "abc"
    assert exc.headers == {"Retry-After": "1"}


def test_direct_error_with_registered_code() -> None:
    problem = SimRemapError("Fila cheia.", code="SIM_WORKER_BUSY").to_problem("r")
    assert (problem.status, problem.code, problem.title) == (
        503,
        "SIM_WORKER_BUSY",
        "Worker de simulação ocupado",
    )


def test_direct_error_unknown_code_raises() -> None:
    with pytest.raises(KeyError):
        SimRemapError("x", code="NOT_REGISTERED_EVER")


def test_problem_detail_schema_limits() -> None:
    with pytest.raises(ValueError, match="code"):
        ProblemDetail(type="t", title="t", status=400, detail="d", code="bad", request_id="r")
    with pytest.raises(ValueError, match="status"):
        ProblemDetail(type="t", title="t", status=302, detail="d", code="ABC", request_id="r")


def test_component_error_modules_list_is_fixed() -> None:
    assert COMPONENT_ERROR_MODULES == (
        "simremap.catalog.errors",
        "simremap.physics.errors",
        "simremap.dyno.errors",
        "simremap.damage.errors",
        "simremap.ecu.errors",
        "simremap.profiles.errors",
        "simremap.telemetry.errors",
        "simremap.scenarios.errors",
    )


@pytest.mark.usefixtures("clean_catalog")
def test_load_component_errors_ignores_missing_and_loads_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = types.ModuleType("simremap_fake_component.errors")
    register_error("TEST_FAKE_LOADED", 422, "Carregado")
    monkeypatch.setitem(sys.modules, "simremap_fake_component.errors", module)
    loaded = load_component_errors(
        ("simremap_missing_component.errors", "simremap_fake_component.errors")
    )
    assert loaded == ["simremap_fake_component.errors"]


def test_load_component_errors_propagates_inner_import_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pkg = tmp_path / "simremap_broken_component"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "errors.py").write_text("import simremap_dependency_that_does_not_exist\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ModuleNotFoundError):
        load_component_errors(("simremap_broken_component.errors",))
