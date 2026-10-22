"""Dicas, eventos locais e taxa de conclusão (T207; scenarios RF-15 a RF-17; premissa OQ-03)."""

from __future__ import annotations

import uuid

from scn_env import ScnEnv
from scn_helpers import RunSpec

from simremap.scenarios.contracts import Hint, HintUnlock
from simremap.scenarios.hints import HintFacts, is_unlocked

HOT = RunSpec(peak_whp=262.0, egt_max_c=962.0, egt_peak_rpm=6100.0)
GOOD = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5)


async def test_hints_unlock_after_failed_submission_and_exhaust(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    url = f"/api/v1/attempts/{attempt['attempt_id']}/hints"
    first = await scn.client.post(url, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"order": 1, "text": first.json()["text"], "remaining": 2}
    locked = await scn.client.post(url, headers=headers)
    assert locked.status_code == 409
    assert locked.json()["code"] == "HINT_LOCKED"

    scn.tune(attempt, HOT, "hot")
    await scn.pull(attempt)
    await scn.pull(attempt)
    failed = await scn.submit(attempt, headers)
    assert failed["passed"] is False
    assert failed["hints_revealed"] == [1]
    second = await scn.client.post(url, headers=headers)
    assert second.status_code == 200 and second.json()["order"] == 2
    third = await scn.client.post(url, headers=headers)  # after_event egt_limit (EGT reprovada)
    assert third.status_code == 200 and third.json()["order"] == 3
    assert third.json()["remaining"] == 0
    done = await scn.client.post(url, headers=headers)
    assert done.status_code == 409
    assert done.json()["code"] == "HINTS_EXHAUSTED"

    scn.tune(attempt, GOOD, "good")
    await scn.pull(attempt)
    await scn.pull(attempt)
    passed = await scn.submit(attempt, headers)
    assert passed["passed"] is True  # as dicas não alteram a aprovação
    assert passed["hints_revealed"] == [1, 2, 3]
    assert passed["total_score"] == 100.0

    kinds = await scn.services.events.kinds_for(attempt["attempt_id"])
    assert kinds.count("attempt_started") == 1
    assert kinds.count("attempt_submitted") == 2
    assert kinds.count("attempt_failed") == 1
    assert kinds.count("attempt_passed") == 1
    assert kinds.count("hint_revealed") == 3
    rows = await scn.services.repo.events(attempt_id=attempt["attempt_id"])
    assert all(
        "nickname" not in r.data_json and "lucas_turbo" not in str(r.data_json) for r in rows
    )

    stats = (await scn.client.get("/api/v1/scenarios/stage1-oem/stats")).json()
    assert stats["started"] == 1 and stats["passed"] == 1
    assert stats["completion_rate_pct"] == 100.0
    assert stats["median_submissions_to_pass"] == 2.0


async def test_completion_rate_80_with_10_started_8_passed(scn: ScnEnv) -> None:
    events = scn.services.events
    for i in range(10):
        attempt_id = str(uuid.uuid4())
        await events.record("attempt_started", "stage1-oem", attempt_id, {})
        if i < 8:
            await events.record(
                "attempt_submitted", "stage1-oem", attempt_id, {"submission_index": 1}
            )
            await events.record("attempt_passed", "stage1-oem", attempt_id, {"submission_index": 1})
        elif i == 8:
            await events.record("attempt_abandoned", "stage1-oem", attempt_id, {})
        else:
            await events.record("attempt_failed", "stage1-oem", attempt_id, {"final": True})
    resp = await scn.client.get("/api/v1/scenarios/stage1-oem/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["completion_rate_pct"] == 80.0
    assert body["started"] == 10
    assert body["passed"] == 8
    assert body["abandoned"] == 1
    assert body["failed_final"] == 1
    # Filtro por datas: intervalo no futuro não tem tentativas.
    future = await scn.client.get(
        "/api/v1/scenarios/stage1-oem/stats", params={"from": "2099-01-01T00:00:00Z"}
    )
    assert future.json()["started"] == 0
    assert future.json()["completion_rate_pct"] is None
    # Métrica do produto só com cenários base (desafios fora).
    await events.record("attempt_started", "challenge-x", str(uuid.uuid4()), {})
    rate = await events.completion_rate_base(["stage1-oem", "stage2-pops-bangs", "standalone-swap"])
    assert rate == 80.0
    missing = await scn.client.get("/api/v1/scenarios/nao-existe/stats")
    assert missing.status_code == 404


def test_unlock_rules() -> None:
    hint = Hint(
        order=1, text="x", unlock=HintUnlock(after_sim_time_s=600, after_event="knock_retard")
    )
    assert not is_unlocked(hint, HintFacts(sim_time_s=700))
    assert not is_unlocked(hint, HintFacts(sim_time_s=100, events=frozenset({"knock_retard"})))
    assert is_unlocked(hint, HintFacts(sim_time_s=700, events=frozenset({"knock_retard"})))
    assert is_unlocked(Hint(order=1, text="livre"), HintFacts())
