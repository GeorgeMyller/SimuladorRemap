"""Contrato do OpenAPI (T078; D-33; RF-03, RF-21)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from simremap.api.registry import collect_routers
from simremap.core.errors import CODE_PATTERN, is_registered, load_component_errors

_CODE_KEYS = ("code", "x-error-code")
_CODE_LISTS = ("x-error-codes",)
_URN = re.compile(r"urn:simremap:problem:([a-z0-9-]+)")


@pytest.fixture(scope="module")
def spec(settings_factory_module: Any) -> dict[str, Any]:
    from simremap.api.main import create_app

    with TestClient(create_app(settings_factory_module())) as tc:
        data: dict[str, Any] = tc.get("/openapi.json").json()
    return data


@pytest.fixture(scope="module")
def settings_factory_module(tmp_path_factory: pytest.TempPathFactory) -> Any:
    from simremap.core.config import Settings

    root = tmp_path_factory.mktemp("openapi")

    def make() -> Settings:
        return Settings(
            _env_file=None,
            env="test",
            data_dir=root,
            static_dir=None,
            database_url=f"sqlite+aiosqlite:///{root.as_posix()}/o.db",
            worker_mode="thread",
            log_level="WARNING",
        )

    return make


def _walk(node: Any) -> list[Any]:
    found = [node]
    if isinstance(node, dict):
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk(value))
    return found


def test_every_path_is_versioned(spec: dict[str, Any]) -> None:
    assert spec["paths"], "OpenAPI sem caminhos"
    for path in spec["paths"]:
        assert path.startswith(("/api/v1/", "/ws/v1/")), path


def test_every_operation_has_registered_tag(spec: dict[str, Any]) -> None:
    tags = {t["name"] for t in spec["tags"]}
    assert tags == {tag for tag, _ in collect_routers()}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            assert operation.get("tags"), (method, path)
            assert set(operation["tags"]) <= tags


def test_documented_codes_are_registered(spec: dict[str, Any]) -> None:
    load_component_errors()
    pattern = re.compile(CODE_PATTERN)
    documented: set[str] = set()
    schemas = dict(spec.get("components", {}).get("schemas", {}))
    schemas.pop("ProblemDetail", None)  # exemplo ilustrativo do formato, não um code em uso
    scanned = {**spec, "components": {**spec.get("components", {}), "schemas": schemas}}
    for node in _walk(scanned):
        if isinstance(node, dict):
            for key in _CODE_KEYS:
                value = node.get(key)
                if isinstance(value, str) and pattern.fullmatch(value):
                    documented.add(value)
            for key in _CODE_LISTS:
                for value in node.get(key) or []:
                    documented.add(str(value))
        elif isinstance(node, str):
            for match in _URN.finditer(node):
                documented.add(match.group(1).upper().replace("-", "_"))
    unregistered = sorted(code for code in documented if not is_registered(code))
    assert unregistered == []


def test_default_error_response_is_problem_detail(spec: dict[str, Any]) -> None:
    for item in spec["paths"].values():
        for operation in item.values():
            default = operation["responses"].get("default")
            assert default is not None
            ref = default["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ProblemDetail")


def test_foundation_endpoints_present(spec: dict[str, Any]) -> None:
    assert "get" in spec["paths"]["/api/v1/health"]
    assert "get" in spec["paths"]["/api/v1/version"]
