"""Turma de 50 alunos (T211; scenarios RF-25, RF-26, RNF-03; G-05; jornada do Prof. Marcos).

1. 50 alunos na estação de aula fazem o ``stage1-oem`` (simulação sintética determinística),
   são aprovados e exportam o pacote da tentativa.
2. 2 pacotes são adulterados (1 dígito num limiar e 1 pico de potência) sem recalcular o hash.
3. O instrutor importa os 50 ficheiros com até 2 uploads em paralelo: 48 importados e 2
   recusados com ``PACKAGE_HASH_MISMATCH`` em ≤ 120 s; a tabela da turma tem 48 linhas e o
   CSV de notas (formato de ``gradesCsv.ts``: ``;`` e vírgula decimal) tem 1 cabeçalho + 48.
"""

from __future__ import annotations

import asyncio
import copy
import csv
import io
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scenarios"))

from scn_env import ScnEnv, make_station, open_station
from scn_helpers import RunSpec

GOOD = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5)
FIXED = (
    "nickname;station;scenario_id;attempt_id;submission;passed;total_score;"
    "evaluation_mismatch;replay_status;package_sha256;imported_at"
)


async def student_package(env: ScnEnv, i: int) -> bytes:
    headers = await env.profile(f"aluno_{i:02d}")
    attempt = await env.start("stage1-oem", headers)
    env.tune(attempt, GOOD, f"aluno-{i}")
    await env.pull(attempt)
    await env.pull(attempt)
    ev = await env.submit(attempt, headers)
    assert ev["passed"] is True
    resp = await env.client.post(
        "/api/v1/packages/export",
        headers=headers,
        json={"kind": "attempt", "attempt_id": attempt["attempt_id"]},
    )
    assert resp.status_code == 200
    return resp.content


def tamper(raw: bytes, how: str) -> bytes:
    pkg: dict[str, Any] = json.loads(raw)
    forged = copy.deepcopy(pkg)
    if how == "threshold":
        crit = forged["payload"]["scenario"]["criteria"]["criteria"]
        next(c for c in crit if c["criterion_id"] == "egt")["threshold"] = 951
    else:
        forged["payload"]["runs"][-1]["summary"]["peak_whp"] = 300.0
    return json.dumps(forged).encode()


def grades_csv(items: list[dict[str, Any]], criteria: list[str]) -> str:
    """Mesmo layout do ``gradesCsv.ts`` (pt-BR: ``;`` e vírgula decimal)."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow([*FIXED.split(";"), *(f"score_{c}" for c in criteria)])
    for item in items:
        ev = item["last_evaluation"] or {}
        scores = {r["criterion_id"]: r["score"] for r in ev.get("results", [])}
        writer.writerow(
            [
                item["nickname"],
                (item["producer_install_id"] or "")[:4],
                item["scenario_id"],
                item["attempt_id"],
                ev.get("submission_index", ""),
                str(ev.get("passed", "")).lower(),
                f"{ev.get('total_score', 0):.1f}".replace(".", ","),
                str(item["evaluation_mismatch"]).lower(),
                item["replay_status"],
                item["package_sha256"],
                item["imported_at"],
                *(f"{scores.get(c, 0):.1f}".replace(".", ",") for c in criteria),
            ]
        )
    return out.getvalue()


async def test_class_of_50_with_2_tampered(
    settings_factory: Callable[..., Any], tmp_path: Path
) -> None:
    async with open_station(make_station(settings_factory, tmp_path, "aula")) as classroom:
        packages = [await student_package(classroom, i) for i in range(50)]
    files = list(packages)
    files[7] = tamper(files[7], "threshold")
    files[31] = tamper(files[31], "peak")

    async with open_station(make_station(settings_factory, tmp_path, "instrutor")) as station:
        prof = await station.profile("prof_marcos", "instructor")
        semaphore = asyncio.Semaphore(2)
        in_flight = 0
        peak = 0
        outcome: dict[int, tuple[int, str | None]] = {}

        async def upload(i: int, body: bytes) -> None:
            nonlocal in_flight, peak
            async with semaphore:
                in_flight += 1
                peak = max(peak, in_flight)
                resp = await station.client.post(
                    "/api/v1/packages/import", headers=prof, content=body
                )
                in_flight -= 1
                code = None if resp.status_code < 400 else resp.json()["code"]
                outcome[i] = (resp.status_code, code)

        started = time.perf_counter()
        await asyncio.gather(*(upload(i, b) for i, b in enumerate(files)))
        elapsed = time.perf_counter() - started
        assert elapsed <= 120.0
        assert peak <= 2
        accepted = [i for i, (status, _) in outcome.items() if status == 201]
        rejected = {i: code for i, (status, code) in outcome.items() if status >= 400}
        assert len(accepted) == 48
        assert rejected == {7: "PACKAGE_HASH_MISMATCH", 31: "PACKAGE_HASH_MISMATCH"}

        page = (
            await station.client.get(
                "/api/v1/attempts",
                headers=prof,
                params={"origin": "imported", "scenario_id": "stage1-oem", "limit": 50},
            )
        ).json()
        assert len(page["items"]) == 48
        assert page["next_cursor"] is None
        assert all(item["last_evaluation"]["passed"] for item in page["items"])
        assert not any(item["evaluation_mismatch"] for item in page["items"])
        scenario = (await station.client.get("/api/v1/scenarios/stage1-oem")).json()
        criteria = [c["criterion_id"] for c in scenario["criteria"]["criteria"]]
        text = grades_csv(page["items"], criteria)
        rows = list(csv.reader(io.StringIO(text), delimiter=";"))
        assert len(rows) == 1 + 48
        assert rows[0][:11] == FIXED.split(";")
        assert rows[0][11:] == [f"score_{c}" for c in criteria]
