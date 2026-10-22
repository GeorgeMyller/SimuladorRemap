"""E-20: aplicação atómica à sessão, ``ack`` ≤ 100 ms e ``TABLE_NOT_LIVE_TUNABLE``.

Fontes: RF-27, RF-28; T147.

O registo de sessões do dyno-bench ainda não existe: os testes usam um fake da
``SessionRegistryPort`` com um ``EcuRuntime`` real a fazer de worker.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from simremap.db.models.calibration import SessionCalibrationRow
from simremap.ecu.apply import handle_apply_command
from simremap.ecu.calibration import CalibrationContent
from simremap.ecu.compiled import compile_calibration
from simremap.ecu.runtime import EcuRuntime
from simremap.ecu.session_port import (
    CalibrationApplyCommand,
    SessionCalibrationInfo,
    SessionRegistryPort,
)
from simremap.physics.contracts import SensorReadings

BASE = "/api/v1/calibrations"
SID = "0f5e9c2a1d2b4c3a9f102b3c4d5e6f70"
DT = 0.001


class FakeWorkerPort:
    """Sessão única com um runtime real; ``apply_calibration`` corre um tick e confirma."""

    def __init__(
        self, runtime: EcuRuntime, sensors: SensorReadings, *, delay_s: float = 0.0
    ) -> None:
        self.runtime = runtime
        self.sensors = sensors
        self.delay_s = delay_s
        self.run_active = False
        self.profile_id = "ft-pro"
        self.vehicle_id = "hatch-20t-gdi"
        self.initial_calibration_id: str | None = None
        self.initial_calibration_version: int | None = None
        self.commands: list[dict[str, object]] = []
        self.cancelled: list[str] = []
        self.hashes: list[str] = []
        self.tick = 0

    async def get_session(self, session_id: str) -> SessionCalibrationInfo | None:
        if session_id != SID:
            return None
        return SessionCalibrationInfo(
            session_id=SID,
            vehicle_id=self.vehicle_id,
            profile_id=self.profile_id,
            run_active=self.run_active,
            initial_calibration_id=self.initial_calibration_id,
            initial_calibration_version=self.initial_calibration_version,
            t_sim_s=self.tick * DT,
        )

    def step(self) -> None:
        s = self.sensors.model_copy(update={"t_sim_s": self.tick * DT, "tick": self.tick})
        self.hashes.append(self.runtime.step(s, DT).status.calibration_hash)
        self.tick += 1

    async def apply_calibration(self, session_id: str, command: CalibrationApplyCommand) -> float:
        cmd = command.to_command()
        self.commands.append(cmd)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        ack = handle_apply_command(self.runtime, cmd)
        assert ack["request_id"] == command.request_id
        self.step()  # a troca entra na fronteira deste tick
        applied = self.runtime.applied_t_sim_s
        assert applied is not None
        return applied

    async def cancel_apply(self, session_id: str, request_id: str) -> None:
        self.cancelled.append(request_id)


def _payload(tb: Any, tables: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "vehicle_id": "hatch-20t-gdi",
        "profile_id": "ft-pro",
        "source": "payload",
        "metadata": {"name": "Stage 1"},
        "tables": tables or tb.full_tables(4),
        "strategies": {"rev_limiter": {"kind": "rev_limiter"}},
    }
    body.update(extra)
    return body


@pytest.fixture
def port(content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any) -> FakeWorkerPort:
    rt = runtime_factory(content_factory(tb.full_tables(4)))
    return FakeWorkerPort(rt, sensors())


async def _setup(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> dict[str, Any]:
    app.state.ecu_session_port = port
    resp = await client.post(BASE, json=_payload(tb))
    assert resp.status_code == 201
    data: dict[str, Any] = resp.json()
    return data


def _apply_url() -> str:
    return f"/api/v1/sessions/{SID}/calibration"


async def test_full_apply_outside_run(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    assert isinstance(port, SessionRegistryPort)
    cal = await _setup(client, app, port, tb)
    for _ in range(3):
        port.step()
    old_hash = port.hashes[-1]
    resp = await client.post(_apply_url(), json={"calibration_id": cal["calibration_id"]})
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["mode"] == "full"
    assert result["version"] == 1 and result["content_hash"] == cal["content_hash"]
    assert result["applied_t_sim_s"] == pytest.approx(3 * DT)
    assert sorted(result["changed_tables"]) == sorted(cal["tables"])
    # Nenhum tick mistura versões: até ao tick 2 a antiga, a partir do 3 a nova (inteira).
    assert port.hashes[:3] == [old_hash] * 3
    assert port.hashes[3] == cal["content_hash"]
    assert port.commands[0]["type"] == "calibration.apply"
    maker = app.state.sessionmaker
    async with maker() as session:
        row = await session.get(SessionCalibrationRow, SID)
    assert row is not None and row.version == 1 and row.content_hash == cal["content_hash"]
    # Reaplicar a mesma versão é idempotente (sem novo comando).
    again = await client.post(
        _apply_url(), json={"calibration_id": cal["calibration_id"], "version": 1}
    )
    assert again.status_code == 200 and again.json()["changed_tables"] == []
    assert len(port.commands) == 1


async def test_ack_timeout_returns_504_and_cancels(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    cal = await _setup(client, app, port, tb)
    port.delay_s = 0.3
    port.step()
    before = port.runtime.compiled.content_hash
    resp = await client.post(_apply_url(), json={"calibration_id": cal["calibration_id"]})
    assert resp.status_code == 504
    problem = resp.json()
    assert problem["code"] == "CALIBRATION_APPLY_TIMEOUT"
    assert port.cancelled == [problem["apply_request_id"]]
    assert port.runtime.compiled.content_hash == before  # nenhum tick usa a versão nova
    maker = app.state.sessionmaker
    async with maker() as session:
        assert await session.get(SessionCalibrationRow, SID) is None


async def test_ack_within_100ms(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    cal = await _setup(client, app, port, tb)
    port.delay_s = 0.05
    resp = await client.post(_apply_url(), json={"calibration_id": cal["calibration_id"]})
    assert resp.status_code == 200


async def test_live_tuning_during_run(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    """RF-28: em puxada só células de tabelas live-tunable (``ve``) passam."""
    cal = await _setup(client, app, port, tb)
    cid = cal["calibration_id"]
    assert (await client.post(_apply_url(), json={"calibration_id": cid})).status_code == 200
    port.run_active = True
    url = f"{BASE}/{cid}/tables"
    patched = await client.patch(
        f"{url}/boost_duty_base",
        json={"base_version": 1, "cells": [{"row": 0, "col": 0, "value": 55}]},
    )
    assert patched.status_code == 200
    resp = await client.post(_apply_url(), json={"calibration_id": cid, "version": 2})
    problem = resp.json()
    assert resp.status_code == 409 and problem["code"] == "TABLE_NOT_LIVE_TUNABLE"
    assert problem["items"] == ["tables.boost_duty_base"]
    assert port.runtime.compiled.version == 1  # a calibração ativa não muda
    revert = await client.put(f"{BASE}/{cid}", json={"base_version": 2, "revert_to_version": 1})
    assert revert.status_code == 200
    ve = await client.patch(
        f"{url}/ve", json={"base_version": 3, "cells": [{"row": 2, "col": 2, "value": 95}]}
    )
    assert ve.status_code == 200
    resp = await client.post(_apply_url(), json={"calibration_id": cid, "version": 4})
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "live_tables"
    assert resp.json()["changed_tables"] == ["ve"]
    assert port.commands[-1]["mode"] == "live_tables"


async def test_strategy_change_refused_during_run(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    """Fluxo D: mudar ``rev_limiter`` em puxada ⇒ 409 com ``strategies.rev_limiter``."""
    cal = await _setup(client, app, port, tb)
    cid = cal["calibration_id"]
    await client.post(_apply_url(), json={"calibration_id": cid})
    body = {
        "base_version": 1,
        "fuel_model": {},
        "tables": tb.full_tables(4),
        "strategies": {"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6500.0}},
        "metadata": {"name": "Stage 1"},
    }
    assert (await client.put(f"{BASE}/{cid}", json=body)).status_code == 200
    port.run_active = True
    resp = await client.post(_apply_url(), json={"calibration_id": cid})
    assert resp.status_code == 409 and resp.json()["items"] == ["strategies.rev_limiter"]


async def test_run_active_uses_initial_calibration(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    cal = await _setup(client, app, port, tb)
    port.run_active = True
    port.initial_calibration_id = None
    resp = await client.post(_apply_url(), json={"calibration_id": cal["calibration_id"]})
    assert resp.status_code == 409 and resp.json()["items"] == ["calibration"]
    port.initial_calibration_id = cal["calibration_id"]
    # A sessão arrancou com a calibração inicial (o worker já a tem compilada).
    initial = CalibrationContent.model_validate(
        {
            k: cal[k]
            for k in (
                "vehicle_id",
                "profile_id",
                "fuel_model",
                "tables",
                "strategies",
                "profile_params",
            )
        }
    )
    port.runtime.swap_calibration(compile_calibration(initial, 4), "full")
    port.step()
    resp = await client.post(_apply_url(), json={"calibration_id": cal["calibration_id"]})
    assert resp.status_code == 200 and resp.json()["changed_tables"] == []


def _content(cal: dict[str, Any]) -> CalibrationContent:
    keys = ("vehicle_id", "profile_id", "fuel_model", "tables", "strategies", "profile_params")
    return CalibrationContent.model_validate({k: cal[k] for k in keys})


async def test_first_live_apply_diffs_against_loaded_version(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    """B2 (003 T032): a sessão arrancou com a v1; a v2 muda uma estratégia. No 1.º aplicar
    em puxada o diff é contra a v1 carregada (409 ``TABLE_NOT_LIVE_TUNABLE``), não contra a
    última versão da calibração inicial (``changed_tables = []`` e erro do worker)."""
    cal = await _setup(client, app, port, tb)
    cid = cal["calibration_id"]
    port.runtime.swap_calibration(compile_calibration(_content(cal), 4), "full")
    port.step()
    port.initial_calibration_id = cid
    port.initial_calibration_version = 1
    body = {
        "base_version": 1,
        "fuel_model": {},
        "tables": tb.full_tables(4),
        "strategies": {"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6500.0}},
        "metadata": {"name": "Stage 1"},
    }
    assert (await client.put(f"{BASE}/{cid}", json=body)).status_code == 200
    port.run_active = True

    resp = await client.post(_apply_url(), json={"calibration_id": cid})

    assert resp.status_code == 409, resp.text
    assert resp.json()["items"] == ["strategies.rev_limiter"]
    assert port.commands == [] and port.runtime.compiled.version == 1
    port.run_active = False
    done = await client.post(_apply_url(), json={"calibration_id": cid})
    assert done.status_code == 200 and done.json()["changed_tables"] == []
    assert port.commands[-1]["mode"] == "full" and port.runtime.compiled.version == 2


async def test_mismatch_and_not_found(
    client: httpx.AsyncClient, app: FastAPI, port: FakeWorkerPort, tb: Any
) -> None:
    cal = await _setup(client, app, port, tb)
    cid = cal["calibration_id"]
    resp = await client.post("/api/v1/sessions/outra/calibration", json={"calibration_id": cid})
    assert resp.status_code == 404 and resp.json()["code"] == "SESSION_NOT_FOUND"
    resp = await client.post(_apply_url(), json={"calibration_id": "nao-existe"})
    assert resp.status_code == 404 and resp.json()["code"] == "CALIBRATION_NOT_FOUND"
    port.profile_id = "oem-stage"
    resp = await client.post(_apply_url(), json={"calibration_id": cid})
    assert resp.status_code == 422 and resp.json()["code"] == "CALIBRATION_PROFILE_MISMATCH"
    port.profile_id = "ft-pro"
    port.vehicle_id = "muscle-v8-sc"
    resp = await client.post(_apply_url(), json={"calibration_id": cid})
    assert resp.status_code == 422 and resp.json()["code"] == "CALIBRATION_VEHICLE_MISMATCH"


async def test_no_port_means_no_sessions(client: httpx.AsyncClient, tb: Any) -> None:
    resp = await client.post(_apply_url(), json={"calibration_id": "x"})
    assert resp.status_code == 404 and resp.json()["code"] == "SESSION_NOT_FOUND"


def test_handle_apply_command_validation(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt: EcuRuntime = runtime_factory(content_factory())
    with pytest.raises(ValueError, match=r"calibration\.apply"):
        handle_apply_command(rt, {"type": "run.start"})
    with pytest.raises(ValueError, match="payload_json"):
        handle_apply_command(rt, {"type": "calibration.apply"})
    content: CalibrationContent = content_factory()
    cmd = CalibrationApplyCommand(
        request_id="r1",
        session_id=SID,
        calibration_id="c1",
        version=3,
        content_hash=compile_calibration(content, 4).content_hash,
        mode="full",
        payload_json=content.model_dump_json(),
    ).to_command()
    ack = handle_apply_command(rt, cmd)
    assert ack == {
        "type": "ack",
        "command": "calibration.apply",
        "request_id": "r1",
        "calibration_id": "c1",
        "version": 3,
        "content_hash": cmd["content_hash"],
    }
    rt.step(sensors(), DT)
    assert rt.compiled.version == 3 and rt.applied_t_sim_s == 0.0
