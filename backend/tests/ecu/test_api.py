"""API de calibrações E-15 a E-19: versões, reversão e concorrência otimista.

Fontes: RF-25, RF-26; D-15; T146.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from simremap.core.errors import SimRemapError
from simremap.ecu import repository as repo_mod
from simremap.ecu.calibration import CalibrationContent
from simremap.ecu.hooks import NullProfileHooks
from simremap.ecu.repository import CalibrationRepository

BASE = "/api/v1/calibrations"


def _payload(tb: Any, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "vehicle_id": "hatch-20t-gdi",
        "profile_id": "ft-pro",
        "source": "payload",
        "metadata": {"name": "Stage 1", "author_nickname": "lucas"},
        "tables": tb.base_tables(),
        "strategies": {"knock_control": {"kind": "knock_control"}},
    }
    body.update(extra)
    return body


async def _create(client: httpx.AsyncClient, tb: Any, **extra: Any) -> dict[str, Any]:
    resp = await client.post(BASE, json=_payload(tb, **extra))
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _cells(n: int, value: float = 2.0) -> list[dict[str, Any]]:
    return [{"row": i // 16, "col": i % 16, "value": value} for i in range(n)]


async def test_empty_list(client: httpx.AsyncClient) -> None:
    resp = await client.get(BASE)
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


async def test_create_returns_location_and_ui_fields(client: httpx.AsyncClient, tb: Any) -> None:
    resp = await client.post(BASE, json=_payload(tb))
    assert resp.status_code == 201
    cal = resp.json()
    assert resp.headers["location"] == f"{BASE}/{cal['calibration_id']}"
    assert cal["version"] == 1 and cal["parent_version"] is None
    assert len(cal["content_hash"]) == 64
    ve = cal["tables"]["ve"]
    assert (ve["min"], ve["max"]) == (0.0, 150.0)
    assert ve["x"]["unit"] == "rev/min" and ve["y"]["source_channel"] == "map_kpa"
    page = (await client.get(BASE, params={"vehicle_id": "hatch-20t-gdi"})).json()
    assert page["total"] == 1
    assert page["items"][0]["content_hash"] == cal["content_hash"]
    assert page["items"][0]["latest_version"] == 1
    assert (await client.get(BASE, params={"profile_id": "oem-stage"})).json()["total"] == 0


async def test_server_recomputes_hash_on_import(client: httpx.AsyncClient, tb: Any) -> None:
    a = await _create(client, tb)
    b = await _create(client, tb, metadata={"name": "Outro nome", "source": "import"})
    assert a["content_hash"] == b["content_hash"]
    assert a["calibration_id"] != b["calibration_id"]


async def test_three_patches_and_revert_make_five_versions(
    client: httpx.AsyncClient, tb: Any
) -> None:
    """RF-05: 3 PATCH + 1 PUT revert_to_version = 1 ⇒ 5 versões e hash v5 == hash v1."""
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}"
    for base in (1, 2, 3):
        resp = await client.patch(
            f"{url}/tables/ve", json={"base_version": base, "op": "add", "cells": _cells(4)}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["version"] == base + 1
    resp = await client.put(url, json={"base_version": 4, "revert_to_version": 1})
    assert resp.status_code == 200, resp.text
    v5 = resp.json()
    assert v5["version"] == 5 and v5["parent_version"] == 4
    assert v5["content_hash"] == cal["content_hash"]
    assert v5["metadata"]["source"] == "revert"
    hist = (await client.get(url, params={"include": "versions"})).json()["versions"]
    assert [v["version"] for v in hist] == [1, 2, 3, 4, 5]
    assert [v["parent_version"] for v in hist] == [None, 1, 2, 3, 4]
    assert hist[0]["content_hash"] == hist[4]["content_hash"] != hist[1]["content_hash"]
    v2 = (await client.get(url, params={"version": 2})).json()
    assert v2["version"] == 2 and v2["tables"]["ve"]["values"][0][0] == 92.0
    assert (await client.get(url)).json()["version"] == 5


async def test_version_conflict_creates_nothing(client: httpx.AsyncClient, tb: Any) -> None:
    """EC-03: o segundo PATCH com o mesmo base_version recebe 409 com latest_version."""
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}"
    first = await client.patch(
        f"{url}/tables/ve", json={"base_version": 1, "cells": _cells(1, 80.0)}
    )
    assert first.status_code == 200
    second = await client.patch(
        f"{url}/tables/ve", json={"base_version": 1, "cells": _cells(1, 70.0)}
    )
    assert second.status_code == 409
    problem = second.json()
    assert problem["code"] == "CALIBRATION_VERSION_CONFLICT"
    assert problem["latest_version"] == 2
    assert second.headers["content-type"].startswith("application/problem+json")
    put = await client.put(url, json={"base_version": 1, "revert_to_version": 1})
    assert put.status_code == 409 and put.json()["code"] == "CALIBRATION_VERSION_CONFLICT"
    hist = (await client.get(url, params={"include": "versions"})).json()["versions"]
    assert len(hist) == 2


async def test_patch_add_four_cells_others_unchanged(client: httpx.AsyncClient, tb: Any) -> None:
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}"
    cells = [{"row": r, "col": c, "value": 2.0} for r, c in ((0, 0), (5, 5), (10, 3), (15, 15))]
    resp = await client.patch(
        f"{url}/tables/ve", json={"base_version": 1, "op": "add", "cells": cells}
    )
    body = resp.json()
    assert resp.status_code == 200
    assert set(body) == {"version", "content_hash", "table"}
    values = body["table"]["values"]
    changed = {(r, c) for r in range(16) for c in range(16) if values[r][c] != 90.0}
    assert changed == {(0, 0), (5, 5), (10, 3), (15, 15)}
    assert values[5][5] == 92.0
    assert body["content_hash"] != cal["content_hash"]
    latest = (await client.get(url)).json()
    assert latest["metadata"]["change_summary"] == "ve: 4 células"


async def test_patch_errors(client: httpx.AsyncClient, tb: Any) -> None:
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}/tables/ve"
    big = await client.patch(
        url, json={"base_version": 1, "cells": [{"row": 0, "col": 0, "value": 1}] * 1025}
    )
    assert big.status_code == 422 and big.json()["code"] == "PATCH_TOO_LARGE"
    oob = await client.patch(
        url, json={"base_version": 1, "cells": [{"row": 0, "col": 31, "value": 1}]}
    )
    assert oob.status_code == 422 and oob.json()["code"] == "PATCH_CELL_OUT_OF_BOUNDS"
    out = await client.patch(
        url, json={"base_version": 1, "cells": [{"row": 4, "col": 9, "value": 151}]}
    )
    problem = out.json()
    assert out.status_code == 422 and problem["code"] == "TABLE_VALUE_OUT_OF_RANGE"
    assert (problem["table_id"], problem["row"], problem["col"]) == ("ve", 4, 9)
    assert (problem["min"], problem["max"], problem["value"]) == (0.0, 150.0, 151.0)
    axis = [1000.0, 900.0, *tb.rpm_axis[2:]]
    mono = await client.patch(url, json={"base_version": 1, "x_values": axis})
    assert mono.status_code == 422 and mono.json()["code"] == "TABLE_AXIS_NOT_MONOTONIC"
    missing = await client.patch(
        f"{BASE}/{cal['calibration_id']}/tables/boost_target", json={"base_version": 1}
    )
    assert missing.status_code == 404 and missing.json()["code"] == "TABLE_NOT_FOUND"
    nocal = await client.patch(f"{BASE}/nao-existe/tables/ve", json={"base_version": 1})
    assert nocal.status_code == 404 and nocal.json()["code"] == "CALIBRATION_NOT_FOUND"
    hist = (
        await client.get(f"{BASE}/{cal['calibration_id']}", params={"include": "versions"})
    ).json()
    assert len(hist["versions"]) == 1  # EC-01/EC-02: nada gravado


async def test_create_validation_codes(client: httpx.AsyncClient, tb: Any) -> None:
    tables = tb.base_tables()
    tables["ve"]["x"]["values"] = [500.0, 1000.0, 1000.0, *tb.rpm_axis[3:]]
    resp = await client.post(BASE, json=_payload(tb, tables=tables))
    assert resp.status_code == 422 and resp.json()["code"] == "TABLE_AXIS_NOT_MONOTONIC"
    tables = tb.base_tables()
    tables["ve"]["unit"] = "ms"
    resp = await client.post(BASE, json=_payload(tb, tables=tables))
    assert resp.status_code == 422 and resp.json()["code"] == "TABLE_UNIT_MISMATCH"
    bad_overrun = {"overrun": {"kind": "overrun", "pops_rpm_min": 7000.0, "pops_rpm_max": 6000.0}}
    resp = await client.post(BASE, json=_payload(tb, strategies=bad_overrun))
    assert resp.status_code == 422 and resp.json()["code"] == "STRATEGY_CONFIG_INVALID"
    ec13 = {
        "two_step": {"kind": "two_step", "target_rpm": 7000.0},
        "rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6500.0},
    }
    resp = await client.post(BASE, json=_payload(tb, strategies=ec13))
    assert resp.status_code == 422 and resp.json()["code"] == "STRATEGY_CONFIG_INVALID"
    resp = await client.post(BASE, json={**_payload(tb), "metadata": {}})
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_FAILED"
    resp = await client.post(BASE, json=_payload(tb, source="clone"))
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_FAILED"


async def test_get_not_found_codes(client: httpx.AsyncClient, tb: Any) -> None:
    resp = await client.get(f"{BASE}/nao-existe")
    assert resp.status_code == 404 and resp.json()["code"] == "CALIBRATION_NOT_FOUND"
    cal = await _create(client, tb)
    resp = await client.get(f"{BASE}/{cal['calibration_id']}", params={"version": 9})
    assert resp.status_code == 404 and resp.json()["code"] == "CALIBRATION_VERSION_NOT_FOUND"
    resp = await client.put(
        f"{BASE}/{cal['calibration_id']}", json={"base_version": 1, "revert_to_version": 9}
    )
    assert resp.status_code == 404 and resp.json()["code"] == "CALIBRATION_VERSION_NOT_FOUND"


async def test_put_replace_and_profile_immutable(client: httpx.AsyncClient, tb: Any) -> None:
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}"
    tables = tb.base_tables()
    tables["ignition_base"] = tb.t3("ignition_base", "ignition_base", "°BTDC", 28.0)
    body = {
        "base_version": 1,
        "fuel_model": {"mode": "speed_density_ve"},
        "tables": tables,
        "strategies": {},
        "profile_params": {"launch_mode": "aggressive"},
        "metadata": {"name": "Stage 2", "change_summary": "avanço +3°"},
    }
    resp = await client.put(url, json=body)
    assert resp.status_code == 200, resp.text
    v2 = resp.json()
    assert v2["version"] == 2 and v2["parent_version"] == 1
    assert v2["profile_params"] == {"launch_mode": "aggressive"}
    summary = (await client.get(BASE)).json()["items"][0]
    assert summary["name"] == "Stage 2" and summary["latest_version"] == 2
    resp = await client.put(url, json={**body, "base_version": 2, "profile_id": "oem-stage"})
    assert resp.status_code == 422 and resp.json()["code"] == "CALIBRATION_PROFILE_IMMUTABLE"
    resp = await client.put(url, json={**body, "base_version": 2, "vehicle_id": "muscle-v8-sc"})
    assert resp.status_code == 422 and resp.json()["code"] == "CALIBRATION_VEHICLE_MISMATCH"
    resp = await client.put(f"{BASE}/nao-existe", json=body)
    assert resp.status_code == 404


async def test_clone_and_reference(client: httpx.AsyncClient, tb: Any, app: FastAPI) -> None:
    src = await _create(client, tb)
    clone = await client.post(
        BASE,
        json={
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "ft-pro",
            "source": "clone",
            "clone_from_id": src["calibration_id"],
            "metadata": {"name": "Clone"},
        },
    )
    assert clone.status_code == 201
    assert clone.json()["content_hash"] == src["content_hash"]
    assert clone.json()["metadata"]["source"] == "clone"
    wrong = await client.post(
        BASE,
        json={
            "vehicle_id": "muscle-v8-sc",
            "profile_id": "ft-pro",
            "source": "clone",
            "clone_from_id": src["calibration_id"],
            "metadata": {"name": "Clone"},
        },
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "CALIBRATION_VEHICLE_MISMATCH"
    wrong = await client.post(
        BASE,
        json={
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "m1-race",
            "source": "clone",
            "clone_from_id": src["calibration_id"],
            "metadata": {"name": "Clone"},
        },
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "CALIBRATION_PROFILE_MISMATCH"
    missing = await client.post(
        BASE,
        json={
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "ft-pro",
            "source": "clone",
            "clone_from_id": "nao-existe",
            "metadata": {"name": "x"},
        },
    )
    assert missing.status_code == 404 and missing.json()["code"] == "CALIBRATION_NOT_FOUND"
    ref = await client.post(
        BASE,
        json={
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "oem-stage",
            "source": "reference",
            "metadata": {"name": "ref"},
        },
    )
    assert ref.status_code == 404 and ref.json()["code"] == "CALIBRATION_NOT_FOUND"
    # Com a calibração de série materializada, ``reference`` copia-a.
    maker = app.state.sessionmaker
    async with maker() as session:
        content = CalibrationContent.model_validate(
            {"vehicle_id": "hatch-20t-gdi", "profile_id": "oem-stage", "tables": tb.base_tables()}
        )
        from simremap.ecu.calibration import CalibrationMetadata

        await CalibrationRepository(session).create(
            content,
            CalibrationMetadata(name="Série", source="oem_stock"),
            calibration_id="stock-hatch-20t-gdi-oem-stage",
        )
    ref = await client.post(
        BASE,
        json={
            "vehicle_id": "hatch-20t-gdi",
            "profile_id": "oem-stage",
            "source": "reference",
            "metadata": {"name": "ref"},
        },
    )
    assert ref.status_code == 201 and ref.json()["metadata"]["source"] == "reference"


class Hooks(NullProfileHooks):
    def supported_strategies(self) -> frozenset[str]:
        return frozenset({"knock_control"})

    def validate_calibration(
        self, cal: CalibrationContent, options: dict[str, bool]
    ) -> list[tuple[str, str]]:
        if cal.profile_params.get("bad"):
            return [("OEM_CHECKSUM_INVALID", "checksum inválido")]
        return []


class Provider:
    def hooks_for(self, profile_id: str) -> Hooks:
        return Hooks(profile_id)


class Vehicles:
    async def vehicle_exists(self, vehicle_id: str) -> bool:
        return vehicle_id == "hatch-20t-gdi"


async def test_profile_hooks_and_vehicle_lookup(
    client: httpx.AsyncClient, app: FastAPI, tb: Any
) -> None:
    app.state.ecu_profile_hooks = Provider()
    app.state.ecu_vehicle_lookup = Vehicles()
    resp = await client.post(BASE, json=_payload(tb, strategies={"two_step": {"kind": "two_step"}}))
    problem = resp.json()
    assert resp.status_code == 422 and problem["code"] == "STRATEGY_NOT_SUPPORTED_BY_PROFILE"
    assert problem["strategy"] == "two_step"
    disabled = {"two_step": {"kind": "two_step", "enabled": False}}
    assert (await client.post(BASE, json=_payload(tb, strategies=disabled))).status_code == 201
    resp = await client.post(BASE, json=_payload(tb, profile_params={"bad": True}))
    assert resp.status_code == 422 and resp.json()["code"] == "OEM_CHECKSUM_INVALID"
    resp = await client.post(BASE, json=_payload(tb, vehicle_id="nao-existe"))
    assert resp.status_code == 404 and resp.json()["code"] == "VEHICLE_NOT_FOUND"


async def test_profile_disabled_by_flag(settings_factory: Any, tb: Any) -> None:
    from asgi_lifespan import LifespanManager

    from simremap.api.main import create_app

    app = create_app(settings_factory(ecu_profiles_enabled=["oem-stage"]))
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(BASE, json=_payload(tb))
    assert resp.status_code == 404 and resp.json()["code"] == "ECU_PROFILE_NOT_FOUND"


async def test_version_limit(
    client: httpx.AsyncClient, tb: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repo_mod, "MAX_CALIBRATION_VERSIONS", 2)
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}"
    assert (
        await client.patch(f"{url}/tables/ve", json={"base_version": 1, "cells": _cells(1, 80)})
    ).status_code == 200
    resp = await client.patch(f"{url}/tables/ve", json={"base_version": 2, "cells": _cells(1, 81)})
    assert resp.status_code == 409 and resp.json()["code"] == "CALIBRATION_VERSION_LIMIT"


async def test_patch_256_cells_latency(client: httpx.AsyncClient, tb: Any) -> None:
    """RNF-03: PATCH de 256 células p95 < 100 ms em SQLite (mediana de 5 medições)."""
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}/tables/ve"
    times = []
    for base in range(1, 6):
        t0 = time.perf_counter()
        resp = await client.patch(
            url, json={"base_version": base, "op": "add", "cells": _cells(256, 0.1)}
        )
        times.append(time.perf_counter() - t0)
        assert resp.status_code == 200
    assert statistics.median(times) < 0.1


class _BrokenSession:
    async def get(self, *args: Any, **kwargs: Any) -> Any:
        raise OperationalError("SELECT", {}, Exception("disk I/O error"))

    async def rollback(self) -> None:
        return None


async def test_ec09_database_unavailable() -> None:
    repo = CalibrationRepository(_BrokenSession())  # type: ignore[arg-type]
    with pytest.raises(SimRemapError) as exc:
        await repo.get("x")
    assert exc.value.error_code == "DATABASE_UNAVAILABLE"
    assert exc.value.headers == {"Retry-After": "2"}
    assert exc.value.error_status == 503


async def test_get_json_round_trips_into_put(client: httpx.AsyncClient, tb: Any) -> None:
    """file-formats seção 3: o JSON do GET (com campos de UI) volta num PUT sem erro."""
    cal = await _create(client, tb)
    url = f"{BASE}/{cal['calibration_id']}"
    got = (await client.get(url)).json()
    body = {k: got[k] for k in ("fuel_model", "tables", "strategies", "profile_params", "metadata")}
    resp = await client.put(url, json={**body, "base_version": got["version"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["content_hash"] == cal["content_hash"]
    imported = await client.post(
        BASE,
        json={
            "vehicle_id": got["vehicle_id"],
            "profile_id": got["profile_id"],
            "source": "payload",
            **{k: got[k] for k in ("fuel_model", "tables", "strategies", "profile_params")},
            "metadata": {**got["metadata"], "source": "import"},
        },
    )
    assert imported.status_code == 201
    assert imported.json()["content_hash"] == cal["content_hash"]
