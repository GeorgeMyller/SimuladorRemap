"""E2E de backend da jornada do Prof. Marcos com duas estações reais (T219; req RF-42).

Duas apps completas (``create_app``, bancos e diretórios de dados próprios, worker ``process``,
catálogo real, ecu-core com a série semeada, telemetria a 1 kHz e dano padrão), com
``steps_per_tick = 10`` para as puxadas correrem mais rápido que o tempo real (dyno RF-23):

1. Estação do instrutor: perfil ``prof_marcos`` (instructor) cria o desafio
   ``challenge-400whp-e27`` (``coupe-30t-i6``, E27) e exporta o ``SignedPackage``.
2. Estação do aluno: importa o desafio (mesmo ``scenario_sha256``), inicia a tentativa
   (baseline automática), aplica um acerto leve, faz 3 ``sweep_pull`` e submete; a avaliação
   aprova só se todos os critérios obrigatórios passarem; exporta o pacote da tentativa.
3. Estação do instrutor: importa o pacote; a avaliação recalculada a partir das evidências
   embutidas tem o mesmo ``evaluation_sha256`` (``evaluation_mismatch = false``) e a
   tentativa aparece em ``GET /attempts?origin=imported`` (dados da pauta/CSV de notas).
4. Logs antes/depois: os logs JSON da puxada base e da última puxada são exportados da
   estação do aluno, importados na do instrutor e comparados (E-27, E-28, E-29).
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from e2e_support import integration_module

from simremap.api.main import create_app
from simremap.scenarios.catalog import example_challenge

CHALLENGE_ID = "challenge-400whp-e27"
ATTEMPT = integration_module("test_stage1_real_attempt")  # poll / run_pull reutilizados


@asynccontextmanager
async def station(
    settings_factory: Callable[..., Any], tmp_path: Path, name: str
) -> AsyncIterator[httpx.AsyncClient]:
    db = tmp_path / f"{name}.db"
    app = create_app(
        settings_factory(
            worker_mode="process",
            data_dir=tmp_path / name,
            database_url=f"sqlite+aiosqlite:///{db.as_posix()}",
        )
    )
    app.state.dyno_task_options = {"steps_per_tick": 10}
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=120.0
        ) as client:
            yield client


async def profile(client: httpx.AsyncClient, nickname: str, role: str) -> dict[str, str]:
    resp = await client.post("/api/v1/profiles", json={"nickname": nickname, "role": role})
    assert resp.status_code == 201, resp.text
    return {"X-Player-Profile-Id": resp.json()["profile_id"]}


def light_tune(cal: dict[str, Any]) -> dict[str, Any]:
    """Acerto leve do aluno: λ 0,82 a plena carga (MAP ≥ 140 kPa) e +10 kPa de pressão alvo."""
    tables: dict[str, Any] = copy.deepcopy(cal["tables"])
    lam = tables["lambda_target"]
    lam["values"] = [
        [min(v, 0.82) if kpa >= 140 else v for v in row]
        for kpa, row in zip(lam["y"]["values"], lam["values"], strict=True)
    ]
    pressure = tables["oem_pressure_target"]
    pressure["values"] = [
        [min(v + 10.0, 400.0) if v >= 150 else v for v in row] for row in pressure["values"]
    ]
    return tables


async def import_log(client: httpx.AsyncClient, raw: bytes) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/logs/import", content=raw, headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def student_attempt(
    student: httpx.AsyncClient, aluno: dict[str, str], out: dict[str, Any]
) -> dict[str, Any]:
    """Tentativa do aluno: baseline, acerto, 3 puxadas, submissão e pacote exportado."""
    started = await student.post(f"/api/v1/scenarios/{CHALLENGE_ID}/attempts", headers=aluno)
    assert started.status_code == 201, started.text
    url = f"/api/v1/attempts/{started.json()['attempt_id']}"
    attempt: dict[str, Any] = await ATTEMPT.poll(
        student, url, aluno, lambda b: b["state"] != "preparing"
    )
    assert attempt["state"] == "in_progress", attempt
    sid, cal_id = attempt["session_id"], attempt["calibration_id"]
    cal = (await student.get(f"/api/v1/calibrations/{cal_id}")).json()
    put = await student.put(
        f"/api/v1/calibrations/{cal_id}",
        json={
            "base_version": cal["version"],
            "fuel_model": cal["fuel_model"],
            "tables": light_tune(cal),
            "strategies": cal["strategies"],
            "profile_params": cal["profile_params"],
            "metadata": {**cal["metadata"], "name": "Acerto da Ana", "change_summary": "λ"},
        },
    )
    assert put.status_code == 200, put.text
    applied = await student.post(
        f"/api/v1/sessions/{sid}/calibration",
        json={"calibration_id": cal_id, "profile_options": {"auto_fix_checksum": True}},
    )
    assert applied.status_code == 200, applied.text
    out["pulls"] = [await ATTEMPT.run_pull(student, sid) for _ in range(3)]
    submit = await student.post(f"{url}/submit", headers=aluno, json={"calibration_id": cal_id})
    assert submit.status_code == 202, submit.text
    out["evaluation"] = await ATTEMPT.poll(
        student, f"{url}/evaluation", aluno, lambda b: b["status"] != "pending"
    )
    out["attempt"] = (await student.get(url, headers=aluno)).json()
    package = await student.post(
        "/api/v1/packages/export",
        headers=aluno,
        json={"kind": "attempt", "attempt_id": attempt["attempt_id"]},
    )
    assert package.status_code == 200, package.text
    out["attempt_package"] = package.json()
    out["attempt_package_raw"] = package.content
    return attempt


@pytest.fixture
async def journey(settings_factory: Callable[..., Any], tmp_path: Path) -> dict[str, Any]:
    t0 = time.perf_counter()
    out: dict[str, Any] = {}
    async with (
        station(settings_factory, tmp_path, "instrutor") as teacher,
        station(settings_factory, tmp_path, "aluno") as student,
    ):
        # 1. Desafio criado e exportado na estação do instrutor.
        marcos = await profile(teacher, "prof_marcos", "instructor")
        created = await teacher.post(
            "/api/v1/scenarios", headers=marcos, json={"scenario": example_challenge()}
        )
        assert created.status_code == 201, created.text
        out["scenario"] = created.json()
        exported = await teacher.post(
            "/api/v1/packages/export",
            headers=marcos,
            json={"kind": "challenge", "scenario_id": CHALLENGE_ID},
        )
        assert exported.status_code == 200, exported.text
        out["challenge_package"] = exported.json()

        # 2. Estação do aluno: importa, tenta, submete e exporta.
        aluno = await profile(student, "aluno_ana", "student")
        imported = await student.post(
            "/api/v1/packages/import", headers=aluno, content=exported.content
        )
        assert imported.status_code == 201, imported.text
        out["challenge_import"] = imported.json()
        out["student_scenario"] = (await student.get(f"/api/v1/scenarios/{CHALLENGE_ID}")).json()

        attempt = await student_attempt(student, aluno, out)

        before = await student.get(f"/api/v1/runs/{attempt['baseline_run_id']}/log")
        after = await student.get(f"/api/v1/runs/{out['pulls'][-1]['run_id']}/log")
        assert before.status_code == 200 and after.status_code == 200
        out["log_sha"] = (before.headers["X-Log-Sha256"], after.headers["X-Log-Sha256"])

        # 3. Estação do instrutor: importa a tentativa e recalcula a avaliação.
        attempt_import = await teacher.post(
            "/api/v1/packages/import", headers=marcos, content=out["attempt_package_raw"]
        )
        assert attempt_import.status_code == 201, attempt_import.text
        out["attempt_import"] = attempt_import.json()
        listed = await teacher.get(
            "/api/v1/attempts", headers=marcos, params={"origin": "imported"}
        )
        assert listed.status_code == 200, listed.text
        out["imported_attempts"] = listed.json()["items"]

        # 4. Logs antes/depois importados e comparados na estação do instrutor.
        log_a = await import_log(teacher, before.content)
        log_b = await import_log(teacher, after.content)
        compared = await teacher.post(
            "/api/v1/logs/compare",
            json={"a": {"log_id": log_a["log_id"]}, "b": {"log_id": log_b["log_id"]}},
        )
        assert compared.status_code == 200, compared.text
        out["imported_logs"] = (log_a, log_b)
        out["comparison"] = compared.json()
        local = await student.post(
            "/api/v1/logs/compare",
            json={
                "a": {"run_id": attempt["baseline_run_id"]},
                "b": {"run_id": out["pulls"][-1]["run_id"]},
            },
        )
        assert local.status_code == 200, local.text
        out["local_comparison"] = local.json()
    out["elapsed_s"] = time.perf_counter() - t0
    print(f"\njornada do Prof. Marcos: {out['elapsed_s']:.1f} s")
    return out


async def test_marcos_journey(journey: dict[str, Any]) -> None:
    scenario = journey["scenario"]
    assert scenario["scenario_id"] == CHALLENGE_ID and scenario["vehicle_id"] == "coupe-30t-i6"
    # Pacote do desafio: mesmo cenário (hash) na estação do aluno.
    pkg = journey["challenge_package"]
    assert pkg["kind"] == "challenge" and len(pkg["sha256"]) == 64
    assert journey["challenge_import"]["kind"] == "challenge"
    assert journey["challenge_import"]["package_sha256"] == pkg["sha256"]
    assert journey["student_scenario"]["scenario_sha256"] == scenario["scenario_sha256"]

    # Tentativa e avaliação objetiva na estação do aluno.
    assert all(p["state"] == "completed" for p in journey["pulls"])
    evaluation = journey["evaluation"]
    assert evaluation["status"] == "completed", evaluation
    results = evaluation["results"]
    assert {r["criterion_id"] for r in results} == {
        "min-whp",
        "egt",
        "knock",
        "integrity",
        "pulls",
        "spread",
    }
    assert evaluation["passed"] is all(r["passed"] for r in results if r["mandatory"])
    measured = {r["criterion_id"]: r["measured"] for r in results}
    print(f"avaliação do aluno: passed={evaluation['passed']} medidas={json.dumps(measured)}")
    assert set(evaluation["evidence_run_ids"]) <= {p["run_id"] for p in journey["pulls"]}

    # Importação no instrutor: avaliação recalculada idêntica.
    imported = journey["attempt_import"]
    assert imported["kind"] == "attempt"
    assert imported["evaluation_mismatch"] is False
    recomputed = imported["recomputed_evaluation"]
    assert recomputed["evaluation_sha256"] == evaluation["evaluation_sha256"]
    assert recomputed["passed"] == evaluation["passed"]
    assert (
        journey["attempt_package"]["payload"]["evaluation"]["evaluation_sha256"]
        == (evaluation["evaluation_sha256"])
    )
    rows = [a for a in journey["imported_attempts"] if a["attempt_id"] == imported["attempt_id"]]
    assert len(rows) == 1 and rows[0]["origin"] == "imported"

    # Logs antes/depois: hash preservado na importação e comparação por bins de RPM.
    log_a, log_b = journey["imported_logs"]
    assert (log_a["sha256"], log_b["sha256"]) == journey["log_sha"]
    comparison = journey["comparison"]
    assert comparison["vehicle_mismatch"] is False and comparison["bins"]
    assert comparison["peak_whp_a"] == pytest.approx(journey["local_comparison"]["peak_whp_a"])
    assert comparison["peak_whp_b"] == pytest.approx(journey["local_comparison"]["peak_whp_b"])
    print(
        f"logs antes/depois: {comparison['peak_whp_a']:.1f} → {comparison['peak_whp_b']:.1f} whp "
        f"({comparison['delta_peak_whp_pct']:+.2f} %), {len(comparison['bins'])} bins"
    )
