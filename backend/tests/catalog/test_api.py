"""E-03 a E-05 (RF-14 a RF-17, RF-29) pela app completa (``create_app`` + lifespan)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from simremap.catalog.service import load_catalog

BASE = "/api/v1/vehicles"
IDS = ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"]


@pytest.fixture
def validated_hatch(catalog_copy: Any) -> Any:
    """Só o hatch validado (os outros 3 voltam a draft), como no fim do Sprint 1."""
    for vid in IDS[1:]:
        catalog_copy.edit(
            f"vehicles/{vid}/vehicle.json",
            lambda d: d.update(validation_status="draft", validated_on=None),
            rehash_after=False,
        )
    catalog_copy.rehash()
    return load_catalog(catalog_copy.root)


class TestList:
    async def test_default_only_validated(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(BASE)
        assert resp.status_code == 200
        body = resp.json()
        # T406: os 4 veículos estão validated (sem include_drafts aparecem todos)
        assert [i["vehicle_id"] for i in body["items"]] == IDS
        assert all(i["validation_status"] == "validated" for i in body["items"])
        assert body["catalog_version"] == "1.1.0"
        assert resp.headers["etag"] == f'"{body["catalog_sha256"]}"'
        assert resp.headers["cache-control"] == "no-cache"

    async def test_include_drafts(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(BASE, params={"include_drafts": "true"})
        items = resp.json()["items"]
        assert [i["vehicle_id"] for i in items] == IDS
        assert all(i["validation_status"] == "validated" for i in items)
        assert len(resp.content) <= 16 * 1024  # RNF-03

    async def test_validated_sprint1(self, client: httpx.AsyncClient, validated_hatch: Any) -> None:
        items = (await client.get(BASE)).json()["items"]
        assert [i["vehicle_id"] for i in items] == ["hatch-20t-gdi"]
        assert items[0]["rated"]["peak_power_whp"] == 220.0

    async def test_invalid_query(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(BASE, params={"include_drafts": "talvez"})
        assert resp.status_code == 422
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert resp.json()["code"] == "VALIDATION_FAILED"


class TestDetail:
    async def test_detail(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"{BASE}/hatch-20t-gdi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["engine"]["compression_ratio"] == 9.6
        assert body["engine"]["calc_displacement_cc"] == pytest.approx(1984.3, abs=0.05)
        assert body["mechanical_limits"]["egt_limit_c"] == 950.0
        assert body["validation_status"] == "validated"
        assert body["validated_on"] == "2026-10-18"
        assert body["estimated_fields"] == sorted(body["estimated_fields"])
        assert "/engine/rod_length_mm" in body["estimated_fields"]
        assert len(body["data_sha256"]) == 64
        assert [f["fuel_id"] for f in body["fuels"]] == ["e27", "podium", "e0"]
        assert body["fuels"][0]["density_g_cc"] == pytest.approx(0.745)
        assert len(resp.content) <= 256 * 1024  # RNF-03

    async def test_not_found(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"{BASE}/inexistente-x")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
        problem = resp.json()
        assert problem["code"] == "VEHICLE_NOT_FOUND"
        assert problem["type"] == "urn:simremap:problem:vehicle-not-found"

    @pytest.mark.parametrize("bad", ["ABC-DEF", "inexistente", "a..b-c"])
    async def test_invalid_id(self, client: httpx.AsyncClient, bad: str) -> None:
        resp = await client.get(f"{BASE}/{bad}")
        assert resp.status_code == 422
        assert resp.json()["code"] == "VEHICLE_ID_INVALID"


class TestReferenceCurves:
    async def test_hatch(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"{BASE}/hatch-20t-gdi/reference-curves")
        assert resp.status_code == 200
        body = resp.json()
        assert body["benchmark_id"] == "reference-benchmark-baseline-v1"
        (curve,) = body["items"]
        assert curve["curve_id"] == "stock-e27"
        assert curve["fuel_id"] == "e27"
        assert len(curve["quantities"]) == 4
        assert curve["points"][0]["power_wheel_whp"] == pytest.approx(83.6, abs=0.1)

    async def test_fuel_filter(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(
            f"{BASE}/hatch-20t-gdi/reference-curves", params={"fuel_id": "e100"}
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "REFERENCE_CURVE_NOT_FOUND"
        resp = await client.get(f"{BASE}/hatch-20t-gdi/reference-curves", params={"fuel_id": "x"})
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_FAILED"

    async def test_calibration_ref_and_missing_vehicle(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(
            f"{BASE}/hatch-20t-gdi/reference-curves", params={"calibration_ref": "stage-1"}
        )
        assert resp.json()["code"] == "REFERENCE_CURVE_NOT_FOUND"
        resp = await client.get(f"{BASE}/abc-def/reference-curves")
        assert resp.json()["code"] == "VEHICLE_NOT_FOUND"

    async def test_same_benchmark_in_four_responses(self, client: httpx.AsyncClient) -> None:
        hashes = set()
        for vid in IDS:
            body = (await client.get(f"{BASE}/{vid}/reference-curves")).json()
            assert body["vehicle_id"] == vid
            hashes.add((body["benchmark_id"], body["benchmark_sha256"], body["catalog_sha256"]))
        assert len(hashes) == 1


class TestEtag:
    @pytest.mark.parametrize(
        "path", [BASE, f"{BASE}/hatch-20t-gdi", f"{BASE}/hatch-20t-gdi/reference-curves"]
    )
    async def test_304(self, client: httpx.AsyncClient, path: str) -> None:
        first = await client.get(path)
        etag = first.headers["etag"]
        for header in (etag, etag.strip('"'), f"W/{etag}", f'"outro", {etag}', "*"):
            again = await client.get(path, headers={"If-None-Match": header})
            assert again.status_code == 304
            assert again.content == b""
            assert again.headers["etag"] == etag
        other = await client.get(path, headers={"If-None-Match": '"diferente"'})
        assert other.status_code == 200

    async def test_etag_changes_with_data(
        self, client: httpx.AsyncClient, catalog_copy: Any
    ) -> None:
        before = (await client.get(BASE)).headers["etag"]
        catalog_copy.edit(
            "vehicles/coupe-30t-i6/vehicle.json", lambda d: d.update(driveline_inertia_kg_m2=3.3)
        )
        load_catalog(catalog_copy.root)  # "novo arranque" com dados alterados
        after = (await client.get(BASE)).headers["etag"]
        assert before != after

    async def test_404_before_304(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"{BASE}/abc-def", headers={"If-None-Match": "*"})
        assert resp.status_code == 404


async def test_openapi_lists_routes(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    for path in ("/api/v1/vehicles", "/api/v1/vehicles/{vehicle_id}",
                 "/api/v1/vehicles/{vehicle_id}/reference-curves"):  # fmt: skip
        assert "get" in spec["paths"][path]
        assert "vehicle-catalog" in spec["paths"][path]["get"]["tags"]
