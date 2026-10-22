"""Lista de bloqueio de marcas: descritores, ProblemDetail e OpenAPI (T159; D-34; RNF-05).

Teste de contrato transversal (alvo do actions.md), movido de ``tests/profiles/``.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from simremap.catalog.service import CatalogService, get_catalog
from simremap.core.errors import catalog as error_catalog
from simremap.profiles.compliance import BLOCKED_TERMS, find_blocked_terms, iter_strings
from simremap.profiles.errors import PROFILE_ERROR_CODES
from simremap.profiles.registry import get_registry


@pytest.fixture(scope="module")
def catalog() -> CatalogService:
    return get_catalog()


def test_blocklist_matching_rules() -> None:
    assert find_blocked_terms("Igual a uma MOTEC") == ["MoTeC"]
    assert find_blocked_terms("software winols") == ["WinOLS"]
    assert find_blocked_terms("mapa m1 tune") == ["M1 Tune"]
    assert find_blocked_terms("M1-Race") == []
    assert find_blocked_terms("OEM-Stage") == []
    assert find_blocked_terms("Nexuss e simosx") == []  # palavra inteira
    assert len(BLOCKED_TERMS) == 16
    assert list(iter_strings({"a": ["b", {"c": "d"}], "n": 1})) == ["a", "b", "c", "d", "n"]


def test_descriptors_have_no_trademarks(catalog: CatalogService) -> None:
    reg = get_registry()
    for pid in reg.profile_ids:
        for vehicle_id in (None, *catalog.vehicle_ids):
            vehicle = catalog.get_vehicle(vehicle_id) if vehicle_id else None
            for package in (None, "base"):
                desc = reg.descriptor_for(pid, vehicle, package)
                found = {
                    t
                    for s in iter_strings(desc.model_dump(mode="json"))
                    for t in find_blocked_terms(s)
                }
                assert not found, (pid, vehicle_id, found)
    assert reg.get("oem-stage").name == "OEM-Stage"


def test_problem_messages_have_no_trademarks() -> None:
    texts = [title for _, _, title in PROFILE_ERROR_CODES]
    texts += [spec.title for spec in error_catalog().values()]
    for text in texts:
        assert not find_blocked_terms(text), text


@pytest.mark.parametrize(
    "path",
    ["/api/v1/ecu-profiles/xx-pro", "/api/v1/sessions/abc/ecu/base-setup"],
)
async def test_problem_details_have_no_trademarks(client: httpx.AsyncClient, path: str) -> None:
    resp = await client.get(path)
    assert resp.status_code >= 400
    assert not find_blocked_terms(resp.text)


async def test_openapi_has_no_trademarks(app: FastAPI, client: httpx.AsyncClient) -> None:
    schema = app.openapi()
    found = {t for s in iter_strings(schema) for t in find_blocked_terms(s)}
    assert not found
