"""Export, import e compare (T169, T334 a T336, T340, T430; tel RF-15, RF-17 a RF-19;
EC-07 a EC-13; RNF-06; E-27 a E-29)."""

from __future__ import annotations

import asyncio
import gzip
import time
from typing import Any

import httpx
import orjson
import pytest
from fastapi.testclient import TestClient
from sqlmodel import delete
from tel_helpers import make_log
from ws_helpers import SHORT, new_session

from simremap.db.models.datalog import DatalogRow
from simremap.telemetry.channels import build_catalog
from simremap.telemetry.compare import bin_log, compare_logs
from simremap.telemetry.contracts import DataLog, LogCompareRequest, LogRef
from simremap.telemetry.datalog import LogData, from_model, json_depth_exceeds, parse_import
from simremap.telemetry.errors import TelemetryError
from simremap.telemetry.logbook import PendingLog
from simremap.telemetry.service import TelemetryService

RUN_A = "01JAB0000000000000000000EA"
RUN_B = "01JAB0000000000000000000EB"
RUN_C = "01JAB0000000000000000000EC"


async def _save(service: TelemetryService, data: LogData) -> None:
    assert service.repository is not None
    await service.repository.save(data, log_id=data.header.run_id, source="simulated")


async def _drop_rows(service: TelemetryService) -> None:
    assert service.repository is not None
    async with service.repository.maker() as session:
        await session.execute(delete(DatalogRow))
        await session.commit()


async def test_json_export_and_import_round_trip(
    tel_client: httpx.AsyncClient, tel_service: TelemetryService
) -> None:
    data = make_log(RUN_A)
    await _save(tel_service, data)
    resp = await tel_client.get(f"/api/v1/runs/{RUN_A}/log")
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-log-sha256"] == data.sha256
    assert resp.headers["content-disposition"] == f'attachment; filename="run-{RUN_A}.json"'
    model = DataLog.model_validate_json(resp.content)
    assert model.sha256 == data.sha256 and model.source == "simulated"
    assert from_model(model).recomputed_sha256() == data.sha256  # repr(float32) exato
    headers = {"content-type": "application/json"}
    dup = await tel_client.post("/api/v1/logs/import", content=resp.content, headers=headers)
    assert dup.status_code == 409 and dup.json()["code"] == "LOG_ALREADY_IMPORTED"
    assert dup.json()["log_id"] == RUN_A
    await _drop_rows(tel_service)  # outra estação
    ok = await tel_client.post("/api/v1/logs/import", content=resp.content, headers=headers)
    assert ok.status_code == 201, ok.text
    summary = ok.json()
    assert summary["sha256"] == data.sha256 and summary["source"] == "imported"
    assert summary["log_id"] == f"imp-{data.sha256[:12]}" and summary["n_samples"] == 15_000
    again = await tel_client.post("/api/v1/logs/import", content=resp.content, headers=headers)
    assert again.status_code == 409 and again.json()["log_id"] == summary["log_id"]
    # Comparação com o importado pelo log_id.
    cmp = await tel_client.post(
        "/api/v1/logs/compare",
        json={"a": {"log_id": summary["log_id"]}, "b": {"log_id": summary["log_id"]}},
    )
    assert cmp.status_code == 200, cmp.text
    assert all(b["delta_torque_nm"] == 0.0 for b in cmp.json()["bins"])
    assert cmp.json()["a"]["source"] == "imported"


async def test_import_validation_errors(tel_client: httpx.AsyncClient) -> None:
    data = make_log(RUN_B, n=2000)
    body = b"".join(__import__("simremap.telemetry.export", fromlist=["iter_json"]).iter_json(data))
    doc = orjson.loads(body)
    headers = {"content-type": "application/json"}
    tampered = {
        **doc,
        "data": {**doc["data"], "rpm": [doc["data"]["rpm"][0] + 1.0, *doc["data"]["rpm"][1:]]},
    }
    resp = await tel_client.post(
        "/api/v1/logs/import", content=orjson.dumps(tampered), headers=headers
    )
    assert resp.status_code == 422 and resp.json()["code"] == "LOG_HASH_MISMATCH"
    assert resp.json()["expected"] == data.sha256 and resp.json()["computed"] != data.sha256
    future = {**doc, "header": {**doc["header"], "format_version": 2}}
    resp = await tel_client.post(
        "/api/v1/logs/import", content=orjson.dumps(future), headers=headers
    )
    assert resp.status_code == 422 and resp.json()["code"] == "LOG_FORMAT_UNSUPPORTED"
    broken = {**doc, "t_sim_s": doc["t_sim_s"][:-1]}
    resp = await tel_client.post(
        "/api/v1/logs/import", content=orjson.dumps(broken), headers=headers
    )
    assert resp.status_code == 422 and resp.json()["code"] == "LOG_SCHEMA_INVALID"
    deep: Any = 0
    for _ in range(40):
        deep = [deep]
    resp = await tel_client.post(
        "/api/v1/logs/import", content=orjson.dumps({"header": {}, "x": deep}), headers=headers
    )
    assert resp.json()["code"] == "LOG_SCHEMA_INVALID"
    wide = {**doc, "data": {f"c{i}": [] for i in range(300)}}
    resp = await tel_client.post("/api/v1/logs/import", content=orjson.dumps(wide), headers=headers)
    assert resp.json()["code"] == "LOG_SCHEMA_INVALID"
    resp = await tel_client.post("/api/v1/logs/import", content=b"{not json", headers=headers)
    assert resp.json()["code"] == "LOG_SCHEMA_INVALID"
    resp = await tel_client.post(
        "/api/v1/logs/import", content=body, headers={"content-type": "text/plain"}
    )
    assert resp.status_code == 415 and resp.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"
    big = b" " * (65 * 1024 * 1024)
    resp = await tel_client.post("/api/v1/logs/import", content=big, headers=headers)
    assert resp.status_code == 413 and resp.json()["code"] == "PAYLOAD_TOO_LARGE"
    # gzip aceite via Content-Encoding.
    gz = gzip.compress(body)
    resp = await tel_client.post(
        "/api/v1/logs/import", content=gz, headers={**headers, "content-encoding": "gzip"}
    )
    assert resp.status_code == 201, resp.text
    resp = await tel_client.post(
        "/api/v1/logs/import", content=body, headers={**headers, "content-encoding": "br"}
    )
    assert resp.status_code == 415


def test_parse_import_limits() -> None:
    bomb = gzip.compress(b" " * (65 * 1024 * 1024))
    with pytest.raises(TelemetryError) as info:
        parse_import(bomb, "gzip")
    assert info.value.error_code == "PAYLOAD_TOO_LARGE"
    with pytest.raises(TelemetryError) as info:
        parse_import(b"garbage", "gzip")
    assert info.value.error_code == "LOG_SCHEMA_INVALID"
    with pytest.raises(TelemetryError):
        parse_import(b"[1, 2]")
    assert json_depth_exceeds({"a": [[[[1]]]]}, limit=3)
    assert not json_depth_exceeds({"a": [1, 2, {"b": 3}]}, limit=3)


async def test_csv_export(tel_client: httpx.AsyncClient, tel_service: TelemetryService) -> None:
    data = make_log(RUN_C)
    await _save(tel_service, data)
    t0 = time.perf_counter()
    resp = await tel_client.get(f"/api/v1/runs/{RUN_C}/log", params={"format": "csv"})
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"].endswith(f'run-{RUN_C}.csv"')
    assert elapsed <= 1.5
    lines = resp.text.split("\n")
    assert lines[-1] == "" and len(lines) - 1 == 15_001
    assert lines[0].startswith("t_sim_s (s),tick (-),rpm (rpm)")
    assert "fuel_cut (flag)" in lines[0] and "egt_c_cyl1 (°C)" in lines[0]
    first = lines[1].split(",")
    assert first[0] == "3.0" and first[1] == "3000" and first[2] == "2000.0"
    sel = await tel_client.get(
        f"/api/v1/runs/{RUN_C}/log",
        params={"format": "csv", "channels": "rpm,fuel_cut,turbo_rpm", "decimate": 10},
    )
    rows = sel.text.strip().split("\n")
    assert rows[0] == "t_sim_s (s),tick (-),rpm (rpm),fuel_cut (flag),turbo_rpm (rpm)"
    assert len(rows) == 1501
    assert rows[1].split(",")[3] == "1" and rows[2].split(",")[3] == "0"
    assert rows[1].endswith(",")  # ausente = campo vazio
    bad = await tel_client.get(f"/api/v1/runs/{RUN_C}/log", params={"format": "xml"})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_FAILED"
    unknown = await tel_client.get(
        f"/api/v1/runs/{RUN_C}/log", params={"format": "csv", "channels": "nope"}
    )
    assert unknown.status_code == 422


def test_csv_cell_formula_guard() -> None:
    from simremap.telemetry.export import csv_cell

    assert csv_cell("=1+1") == "'=1+1"
    assert csv_cell("@cmd") == "'@cmd"
    assert csv_cell('a,"b"') == '"a,""b"""'
    assert csv_cell("rpm (rpm)") == "rpm (rpm)"


async def test_log_states_not_found_not_ready_and_corrupted(
    tel_client: httpx.AsyncClient, tel_service: TelemetryService, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = await tel_client.get("/api/v1/runs/01JAB0000000000000000000ZZ/log")
    assert resp.status_code == 404 and resp.json()["code"] == "RUN_NOT_FOUND"
    pending = PendingLog(
        run_id="01JAB0000000000000000000PP",
        session_id="s",
        start_tick=0,
        sim_hz=1000,
        catalog=build_catalog(4, True),
        meta=None,
    )
    tel_service.logbook.pending[pending.run_id] = pending
    resp = await tel_client.get(f"/api/v1/runs/{pending.run_id}/log")
    assert resp.status_code == 409 and resp.json()["code"] == "LOG_NOT_READY"
    del tel_service.logbook.pending[pending.run_id]
    states = {"01JAB0000000000000000000RR": "running", "01JAB0000000000000000000CC": "completed"}

    async def fake_state(run_id: str) -> str | None:
        return states.get(run_id)

    monkeypatch.setattr(tel_service, "run_state", fake_state)
    resp = await tel_client.get("/api/v1/runs/01JAB0000000000000000000RR/log")
    assert resp.status_code == 409 and resp.json()["code"] == "LOG_NOT_READY"
    resp = await tel_client.get("/api/v1/runs/01JAB0000000000000000000CC/log")
    assert resp.status_code == 404 and resp.json()["code"] == "LOG_NOT_FOUND"
    # Arquivo corrompido no disco ⇒ 500 LOG_CORRUPTED.
    data = make_log("01JAB0000000000000000000CD", n=500)
    await _save(tel_service, data)
    assert tel_service.repository is not None
    path = tel_service.repository.data_dir / tel_service.repository.relative_path(
        "01JAB0000000000000000000CD"
    )
    path.write_bytes(gzip.compress(b"SIMLOG1\n" + b"\x00" * 64))
    resp = await tel_client.get("/api/v1/runs/01JAB0000000000000000000CD/log")
    assert resp.status_code == 500 and resp.json()["code"] == "LOG_CORRUPTED"
    path.unlink()
    resp = await tel_client.get("/api/v1/runs/01JAB0000000000000000000CD/log")
    assert resp.status_code == 404 and resp.json()["code"] == "LOG_NOT_FOUND"


async def test_storage_full_keeps_log_in_memory_for_export(
    tel_client: httpx.AsyncClient, tel_service: TelemetryService, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tel_service.repository
    assert repo is not None
    repo.retry_delays = (0.0, 0.0, 0.0)
    import simremap.telemetry.repository as repo_module

    def full_disk(path: Any, data: LogData) -> int:
        raise OSError("disco cheio")

    monkeypatch.setattr(repo_module, "write_simlog", full_disk)
    data = make_log("01JAB0000000000000000000ME", n=400)
    book = tel_service.logbook
    book.memory[data.header.run_id] = (data, asyncio.get_running_loop().time() + 60.0)
    resp = await tel_client.get("/api/v1/runs/01JAB0000000000000000000ME/log")
    assert resp.status_code == 507 and resp.json()["code"] == "STORAGE_FULL"
    monkeypatch.undo()
    resp = await tel_client.get("/api/v1/runs/01JAB0000000000000000000ME/log")
    assert resp.status_code == 200 and resp.headers["x-log-sha256"] == data.sha256
    assert book.in_memory("01JAB0000000000000000000ME") is None  # gravado na nova tentativa
    book.memory["x"] = (data, -1.0)
    assert book.in_memory("x") is None  # expirado (60 s)


async def test_compare_endpoint(
    tel_client: httpx.AsyncClient, tel_service: TelemetryService
) -> None:
    await _save(tel_service, make_log(RUN_A))
    await _save(tel_service, make_log(RUN_B, torque_offset=10.0, seed=8))
    await _save(tel_service, make_log(RUN_C, rpm_range=(7000.0, 8000.0), seed=9))
    t0 = time.perf_counter()
    same = await tel_client.post(
        "/api/v1/logs/compare", json={"a": {"run_id": RUN_A}, "b": {"run_id": RUN_A}}
    )
    assert time.perf_counter() - t0 < 0.5
    assert same.status_code == 200, same.text
    body = same.json()
    assert body["bins"] and all(b["delta_torque_nm"] == 0.0 for b in body["bins"])
    assert body["max_abs_delta"]["whp"] == 0.0 and body["vehicle_mismatch"] is False
    plus = await tel_client.post(
        "/api/v1/logs/compare",
        json={"a": {"run_id": RUN_A}, "b": {"run_id": RUN_B}, "bin_rpm": 100},
    )
    bins = plus.json()["bins"]
    assert len(bins) == 40 and [b["rpm_bin"] for b in bins] == sorted(b["rpm_bin"] for b in bins)
    assert all(abs(b["delta_torque_nm"] - 10.0) <= 0.05 for b in bins)
    assert bins[0]["knock_intensity_max_a"] == pytest.approx(0.2)
    none = await tel_client.post(
        "/api/v1/logs/compare", json={"a": {"run_id": RUN_A}, "b": {"run_id": RUN_C}}
    )
    assert none.status_code == 422 and none.json()["code"] == "LOG_COMPARE_NO_OVERLAP"
    missing = await tel_client.post(
        "/api/v1/logs/compare",
        json={"a": {"run_id": RUN_A}, "b": {"run_id": "01JAB0000000000000000000ZZ"}},
    )
    assert missing.status_code == 404 and missing.json()["code"] == "LOG_NOT_FOUND"
    bad = await tel_client.post("/api/v1/logs/compare", json={"a": {}, "b": {"run_id": RUN_A}})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_FAILED"


def test_compare_rules() -> None:
    a = make_log(RUN_A, n=3000)
    other = make_log(RUN_B, n=3000, vehicle_id="muscle-v8-sc")
    result = compare_logs(
        a, other, LogCompareRequest(a=LogRef(run_id=RUN_A), b=LogRef(run_id=RUN_B))
    )
    assert result.vehicle_mismatch is True and result.delta_peak_whp_pct == 0.0
    hold = make_log(RUN_C, n=3000, phase="cells")  # steady_state_hold sem varrimento
    with pytest.raises(TelemetryError) as info:
        compare_logs(a, hold, LogCompareRequest(a=LogRef(run_id=RUN_A), b=LogRef(run_id=RUN_C)))
    assert info.value.error_code == "LOG_COMPARE_NO_OVERLAP"
    with pytest.raises(TelemetryError) as info:
        bin_log(a, 100, 2, 5)
    assert info.value.error_code == "VALIDATION_FAILED"
    few = bin_log(a, 500, None, 1000)
    assert few == {}  # menos amostras que o mínimo por bin
    assert set(bin_log(a, 500, 1, 5)) == {2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500}


def test_real_run_log_is_written_and_exported(e2e_client: TestClient) -> None:
    sid = new_session(e2e_client)
    resp = e2e_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)
    run_id = resp.json()["run_id"]
    early = e2e_client.get(f"/api/v1/runs/{run_id}/log")
    assert early.status_code == 409 and early.json()["code"] == "LOG_NOT_READY"
    deadline = time.monotonic() + 60
    while True:
        log_resp = e2e_client.get(f"/api/v1/runs/{run_id}/log")
        if log_resp.status_code == 200 or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert log_resp.status_code == 200, log_resp.text
    model = DataLog.model_validate_json(log_resp.content)
    header = model.header
    assert header.run_id == run_id and header.session_id == sid
    assert header.vehicle_id == "hatch-20t-gdi" and header.terminal_state == "completed"
    run = e2e_client.get(f"/api/v1/runs/{run_id}", params={"include_curve": "false"}).json()
    assert header.calibration_hash == run["calibration_hash"] and header.seed == 3
    assert header.n_samples == run["ended_at_tick"] - run["started_at_tick"] + 1
    states = [e.payload["state"] for e in header.events if e.type == "run.state"]
    assert states[0] == "arming" and states[-1] == "completed"
    cmp = e2e_client.post(
        "/api/v1/logs/compare", json={"a": {"run_id": run_id}, "b": {"run_id": run_id}}
    )
    assert cmp.status_code == 200, cmp.text
    assert cmp.json()["bins"]
