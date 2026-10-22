"""Determinismo do laço (dyno G-03, RF-23, RNF-03; simulation-bus 5)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from dyno_helpers import make_task, run_to_result

SHORT = {"run_type": "sweep_pull", "end_rpm": 3500, "ramp_rate_rpm_s": 600}


def _hash(seed: int, **over: Any) -> tuple[str, str]:
    task = make_task(seed=seed, **over)
    out = run_to_result(task, dict(SHORT))
    assert out.run.curve_sha256 is not None
    return out.run.curve_sha256, task.session.physics.state_digest()


def test_g03_same_seed_same_curve_hash_and_state_digest() -> None:
    first = _hash(1234)
    second = _hash(1234)
    assert first == second


def test_different_seed_changes_the_noise_and_the_hash() -> None:
    assert _hash(1)[0] != _hash(2)[0]


def test_steps_per_tick_does_not_change_results() -> None:
    """Acelerar o tempo de parede (vários passos por tick do host) não altera a curva."""
    one = make_task(seed=5)
    many = make_task(seed=5, steps_per_tick=7)
    for task in (one, many):
        task.handle_command(
            {"type": "run.start", "run_id": "01JAB0000000000000000000AA", "request": SHORT}
        )
    results = []
    for task in (one, many):
        done = None
        for _ in range(60_000):
            task.tick()
            for raw in task.drain_outputs():
                if b'"run.result"' in raw[:64]:
                    done = raw
            if done is not None:
                break
        results.append(done)
    assert results[0] is not None and results[0] == results[1]


async def wait_terminal(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    for _ in range(600):
        body: dict[str, Any] = (
            await client.get(f"/api/v1/runs/{run_id}", params={"curve": "raw"})
        ).json()
        if body["state"] in ("completed", "aborted", "engine_failed"):
            return body
        await asyncio.sleep(0.1)
    raise AssertionError("a puxada não terminou")


async def test_rf23_generated_seed_reproduces_curve(dyno_client: httpx.AsyncClient) -> None:
    hashes = []
    seed: int | None = None
    for _ in range(2):
        body: dict[str, Any] = {"vehicle_id": "hatch-20t-gdi"}
        if seed is not None:
            body["seed"] = seed
        created = (await dyno_client.post("/api/v1/sessions", json=body)).json()
        seed = int(created["seed"])
        sid = created["session_id"]
        run = (await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)).json()
        done = await wait_terminal(dyno_client, run["run_id"])
        assert done["state"] == "completed"
        hashes.append(done["curve_sha256"])
        assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 204
    assert hashes[0] == hashes[1]
