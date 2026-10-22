"""Fluxo do Sprint 2 por REST (T127; dyno RF-14, RF-20; damage RF-19, RF-21; jornada do Lucas).

1. Sessão no ``hatch-20t-gdi`` (física calibrada da fixture) e puxada base ``completed``.
2. Calibração exagerada (alvo de boost 280 kPa abs a plena carga e +8° de avanço) criada no
   ecu-core e aplicada à sessão pela ``SessionRegistryPort`` do dyno.
3. ``sweep_pull`` ⇒ ``engine_failed`` com ``failure_event_id`` e laudo forense.
4. Nova puxada ⇒ 409 ``ENGINE_DESTROYED``; ``POST .../engine/restore`` ⇒ motor intacto.
5. Calibração de série reaplicada e puxada ``completed``.

O dano usa ``mechanical`` (bielas, pressão, bronzinas): a falha esperada é ``rod_failure``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from dyno_helpers import modified_content, stock_content

from simremap.ecu.calibration import CalibrationContent

TERMINAL = {"completed", "aborted", "engine_failed"}


async def wait_terminal(
    client: httpx.AsyncClient, run_id: str, timeout_s: float = 120.0
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        body: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if body["state"] in TERMINAL:
            return body
        await asyncio.sleep(0.1)
    raise AssertionError("a puxada não terminou")


async def create_calibration(
    client: httpx.AsyncClient, content: CalibrationContent, name: str
) -> str:
    data = content.model_dump(mode="json")
    body = {
        "vehicle_id": "hatch-20t-gdi",
        "profile_id": "oem-stage",
        "metadata": {"name": name},
        "source": "payload",
        "fuel_model": data["fuel_model"],
        "tables": data["tables"],
        "strategies": data["strategies"],
        "profile_params": data["profile_params"],
    }
    resp = await client.post("/api/v1/calibrations", json=body)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["calibration_id"])


async def apply(client: httpx.AsyncClient, session_id: str, calibration_id: str) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/sessions/{session_id}/calibration", json={"calibration_id": calibration_id}
    )
    assert resp.status_code == 200, resp.text
    result: dict[str, Any] = resp.json()
    return result


async def test_sprint2_failure_restore_and_recovery(integration_client: httpx.AsyncClient) -> None:
    client = integration_client
    session = await client.post(
        "/api/v1/sessions", json={"vehicle_id": "hatch-20t-gdi", "seed": 42}
    )
    assert session.status_code == 201, session.text
    sid = session.json()["session_id"]

    # 1. Puxada base de série.
    base = await client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "baseline_pull"})
    assert base.status_code == 202
    base_run = await wait_terminal(client, base.json()["run_id"])
    assert base_run["state"] == "completed"
    assert 209.0 <= base_run["summary"]["peak_whp"] <= 231.0
    assert (await client.get(f"/api/v1/sessions/{sid}")).json()["baseline_run_id"] == base_run[
        "run_id"
    ]

    # 2. Calibração exagerada aplicada pela porta do ecu-core.
    hot = await create_calibration(
        client, modified_content(boost_kpa=280.0, ignition_offset_deg=8.0), "Stage exagerado"
    )
    applied = await apply(client, sid, hot)
    assert applied["mode"] == "full" and applied["applied_t_sim_s"] > 0

    # 3. Falha catastrófica na puxada.
    sweep = await client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
    assert sweep.status_code == 202
    failed = await wait_terminal(client, sweep.json()["run_id"])
    assert failed["state"] == "engine_failed"
    assert failed["abort_reason"] == "catastrophic_failure"
    assert failed["summary"]["failure_event_id"]
    url = failed["summary"]["forensic_report_url"]
    assert url == f"/api/v1/runs/{failed['run_id']}/forensic-report"
    assert failed["calibration_hash"] != base_run["calibration_hash"]
    state = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert state["engine_locked"] is True and state["state"] == "engine_locked"
    report: dict[str, Any] = {}
    for _ in range(100):
        resp = await client.get(url)
        if resp.status_code == 200:
            report = resp.json()
            break
        assert resp.status_code == 409 and resp.json()["code"] == "FORENSIC_REPORT_PENDING"
        await asyncio.sleep(0.1)
    assert report["run_id"] == failed["run_id"]
    assert report["failure_event"]["failure_event_id"] == failed["summary"]["failure_event_id"]
    health = (await client.get(f"/api/v1/sessions/{sid}/engine/health")).json()
    assert health["engine_locked"] is True and health["intact"] is False

    # 4. Motor destruído até restaurar.
    refused = await client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
    assert refused.status_code == 409 and refused.json()["code"] == "ENGINE_DESTROYED"
    restored = await client.post(
        f"/api/v1/sessions/{sid}/engine/restore", json={"note": "motor novo"}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["engine_locked"] is False
    assert restored.json()["intact"] is True and restored.json()["restore_count"] == 1
    assert (await client.get(f"/api/v1/sessions/{sid}")).json()["state"] == "ready"

    # 5. Série de volta e puxada concluída.
    stock = await create_calibration(client, stock_content(), "Série")
    await apply(client, sid, stock)
    final = await client.post(
        f"/api/v1/sessions/{sid}/runs",
        json={"run_type": "sweep_pull", "end_rpm": 4000, "ramp_rate_rpm_s": 600},
    )
    assert final.status_code == 202, final.text
    done = await wait_terminal(client, final.json()["run_id"])
    assert done["state"] == "completed"
    assert done["calibration_hash"] == base_run["calibration_hash"]
