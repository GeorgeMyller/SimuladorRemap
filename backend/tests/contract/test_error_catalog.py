"""Contrato do catálogo de erros (T076; RF-06; D-13 a D-16; rest-api 4.10)."""

from __future__ import annotations

import re

import pytest

from simremap.core.errors import (
    CODE_PATTERN,
    RETIRED_CODES,
    ErrorCodeConflict,
    ErrorCodeInvalid,
    catalog,
    catalog_sha256,
    load_component_errors,
    problem_type,
    register_error,
)

FOUNDATION = {
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


@pytest.fixture(scope="module", autouse=True)
def _components_loaded() -> None:
    load_component_errors()


def test_every_code_matches_pattern_and_has_http_error_status() -> None:
    pattern = re.compile(CODE_PATTERN)
    for code, spec in catalog().items():
        assert pattern.fullmatch(code), code
        assert spec.code == code
        assert 400 <= spec.status <= 599, code
        assert 1 <= len(spec.title) <= 120, code
        assert spec.type == problem_type(code)
        assert spec.type.startswith("urn:simremap:problem:")


def test_codes_are_unique_case_insensitive() -> None:
    codes = list(catalog())
    assert len(codes) == len({c.upper() for c in codes})
    types = [problem_type(c) for c in codes]
    assert len(types) == len(set(types))


def test_foundation_codes_have_fixed_status() -> None:
    entries = catalog()
    for code, status in FOUNDATION.items():
        assert entries[code].status == status


def test_retired_codes_absent_and_refused() -> None:
    assert RETIRED_CODES == {
        "VALIDATION_ERROR",
        "RUN_ALREADY_ACTIVE",
        "CALIBRATION_REVISION_CONFLICT",
        "TABLE_LOCKED_DURING_RUN",
        "STORAGE_UNAVAILABLE",
    }
    assert RETIRED_CODES.isdisjoint(catalog())
    for code in RETIRED_CODES:
        with pytest.raises(ErrorCodeInvalid, match="aposentado"):
            register_error(code, 409, "x")


def test_conflicting_registration_fails() -> None:
    with pytest.raises(ErrorCodeConflict):
        register_error("SIM_WORKER_BUSY", 429, "Ocupado")


def test_transversal_codes_from_r1() -> None:
    assert catalog()["SIM_CAPACITY_EXCEEDED"].status == 409
    if "ECU_PROFILE_NOT_FOUND" in catalog():  # registado por ecu-profiles
        assert catalog()["ECU_PROFILE_NOT_FOUND"].status == 404


def test_catalog_sha256_is_stable() -> None:
    first = catalog_sha256()
    load_component_errors()
    assert catalog_sha256() == first
    assert re.fullmatch(r"[0-9a-f]{64}", first)
