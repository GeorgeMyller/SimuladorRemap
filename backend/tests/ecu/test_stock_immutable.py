"""Calibrações de fábrica (``stock-*``) só de leitura nas rotas (002 T007/T017; D-03)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from simremap.ecu.seed_stock import StockCalibrationSource, seed_stock_calibrations

BASE = "/api/v1/calibrations"
STOCK_ID = "stock-hatch-20t-gdi-oem-stage"
DETAIL = "Calibrações de fábrica são somente leitura; clone antes de editar."


async def _seed(app: FastAPI, tb: Any) -> dict[str, Any]:
    payload = {
        "fuel_model": {"mode": "speed_density_ve"},
        "tables": tb.base_tables(),
        "strategies": {},
        "metadata": {"name": "Série hatch", "source": "oem_stock"},
    }
    source = StockCalibrationSource("hatch-20t-gdi", "oem-stage", payload)
    report = await seed_stock_calibrations(app.state.sessionmaker, [source])
    assert report.created == [STOCK_ID]
    return payload


async def _v1(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(f"{BASE}/{STOCK_ID}", params={"include": "versions"})
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _assert_refused(resp: httpx.Response) -> None:
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "CALIBRATION_STOCK_IMMUTABLE"
    assert body["detail"] == DETAIL
    assert body["calibration_id"] == STOCK_ID


async def test_put_replace_revert_and_patch_on_stock_are_refused(
    client: httpx.AsyncClient, app: FastAPI, tb: Any
) -> None:
    await _seed(app, tb)
    before = await _v1(client)
    table_id = next(iter(before["tables"]))

    replace = await client.put(
        f"{BASE}/{STOCK_ID}",
        json={
            "base_version": 1,
            "fuel_model": before["fuel_model"],
            "tables": before["tables"],
            "strategies": before["strategies"],
            "profile_params": before["profile_params"],
            "metadata": {**before["metadata"], "name": "Editada"},
        },
    )
    _assert_refused(replace)
    revert = await client.put(
        f"{BASE}/{STOCK_ID}", json={"base_version": 1, "revert_to_version": 1}
    )
    _assert_refused(revert)
    patch = await client.patch(
        f"{BASE}/{STOCK_ID}/tables/{table_id}",
        json={"base_version": 1, "op": "add", "cells": [{"row": 0, "col": 0, "value": 1.0}]},
    )
    _assert_refused(patch)

    after = await _v1(client)
    assert after["version"] == 1
    assert after["content_hash"] == before["content_hash"]
    assert after["tables"] == before["tables"]
    assert len(after["versions"]) == 1


async def test_stock_stays_readable_and_clonable(
    client: httpx.AsyncClient, app: FastAPI, tb: Any
) -> None:
    await _seed(app, tb)
    stock = await _v1(client)
    clone = await client.post(
        BASE,
        json={
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "oem-stage",
            "source": "clone",
            "clone_from_id": STOCK_ID,
            "metadata": {"name": "Cópia da série"},
        },
    )
    assert clone.status_code == 201, clone.text
    assert clone.json()["content_hash"] == stock["content_hash"]
    ref = await client.post(
        BASE,
        json={
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "oem-stage",
            "source": "reference",
            "metadata": {"name": "Referência"},
        },
    )
    assert ref.status_code == 201, ref.text
    cal_id = clone.json()["calibration_id"]
    table_id = next(iter(stock["tables"]))
    edited = await client.patch(
        f"{BASE}/{cal_id}/tables/{table_id}",
        json={"base_version": 1, "op": "add", "cells": [{"row": 0, "col": 0, "value": 1.0}]},
    )
    assert edited.status_code == 200, edited.text
