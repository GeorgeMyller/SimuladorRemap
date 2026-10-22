"""``PhysicsOnlyTask`` (T408): física real headless, frames a 50 FPS, nos dois modos do worker."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

import orjson
import pytest

from simremap.catalog.loader import load_catalog_data
from simremap.core.worker.host import SimWorkerHost, WorkerHandle
from simremap.core.worker.physics_task import PhysicsOnlyTask
from simremap.core.worker.protocol import SimTask, WorkerConfig

TASK = "simremap.core.worker.physics_task:PhysicsOnlyTask"


def _setup(**options: Any) -> PhysicsOnlyTask:
    task = PhysicsOnlyTask()
    task.setup(orjson.dumps(options))
    return task


def _decode(task: PhysicsOnlyTask) -> list[dict[str, Any]]:
    return [orjson.loads(raw) for raw in task.drain_outputs()]


def _run(task: PhysicsOnlyTask, ticks: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _ in range(ticks):
        task.tick()
        out += _decode(task)
    return out


def test_protocol_and_default_vehicle() -> None:
    task = PhysicsOnlyTask()
    assert isinstance(task, SimTask)
    task.setup(b"")
    first = _decode(task)
    assert first[0]["type"] == "run.state"
    assert first[0]["payload"] == {"state": "idle", "vehicle_id": "hatch-20t-gdi", "fuel_id": "e27"}
    assert task.sim_hz == 1000
    assert task.fps == 50


def test_frames_at_50fps_and_real_physics() -> None:
    task = _setup(rpm=4000.0, noise=False, sim_hz=1000, fps=50)
    _decode(task)
    items = _run(task, 2000)  # 2 s simulados
    frames = [i for i in items if i["type"] == "telemetry.frame"]
    # 1.º frame no 1.º tick (índice 0) e depois um a cada 20 ticks: 50 FPS
    assert [f["payload"]["frame_index"] for f in frames] == list(range(101))
    assert frames[1]["t_sim_s"] == pytest.approx(0.02)
    assert frames[-1]["t_sim_s"] == pytest.approx(2.0)
    last = frames[-1]["payload"]
    assert last["rpm"] == pytest.approx(4000.0, abs=50.0)
    assert last["torque_nm"] > 50.0  # combustão real a plena carga
    assert last["map_kpa"] > 100.0
    assert 0.7 < last["lambda_collector"] < 1.1


def test_commands_and_teardown_digest() -> None:
    task = _setup(vehicle_id="muscle-v8-sc", rpm=3000.0, noise=False)
    _decode(task)
    task.handle_command({"type": "set_rpm", "rpm": 3500.0})
    task.handle_command({"type": "set_throttle", "throttle_pct": 20.0})
    task.handle_command({"type": "set_throttle", "throttle_pct": None})
    task.handle_command({"type": "echo", "value": 3})
    task.handle_command({"type": "run.state", "state": "running"})
    task.handle_command({"type": "unknown"})
    acks = _decode(task)
    assert [a["payload"].get("command") for a in acks if a["type"] == "ack"] == [
        "set_rpm", "set_throttle", "set_throttle", "echo", "unknown",
    ]  # fmt: skip
    assert acks[0]["payload"]["rpm"] == 3500.0
    assert acks[1]["payload"]["throttle_pct"] == 20.0
    assert acks[-1]["payload"]["ignored"] is True
    _run(task, 10)
    task.teardown()
    closed = _decode(task)[-1]
    assert closed["payload"]["state"] == "closed"
    assert closed["payload"]["ticks"] == 10
    assert len(closed["payload"]["state_digest"]) == 64


def test_explicit_specs_are_deterministic() -> None:
    catalog = load_catalog_data()
    entry = catalog.vehicles["coupe-30t-i6"]
    payload = {
        "vehicle": entry.spec.model_dump(mode="json"),
        "fuel": catalog.fuels["e27"].model_dump(mode="json"),
        "rpm": 5000.0,
        "seed": 7,
        "sim_hz": 500,
    }
    digests = []
    for _ in range(2):
        task = _setup(**payload)
        _run(task, 300)
        task.teardown()
        digests.append(_decode(task)[-1]["payload"]["state_digest"])
    assert digests[0] == digests[1]


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"vehicle_id": "nao-existe"}, "veículo desconhecido"),
        ({"fuel_id": "e100"}, "não permitido"),
        ({"rpm": 100.0}, "rpm fora"),
        ({"sim_hz": "1000"}, "sim_hz deve ser numérico"),
        ({"vehicle": {"vehicle_id": "x"}}, "'fuel' é obrigatório"),
    ],
)
def test_invalid_setup(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _setup(**options)
    with pytest.raises(ValueError, match="objeto JSON"):
        PhysicsOnlyTask().setup(b"[1]")


def test_tick_without_setup() -> None:
    with pytest.raises(RuntimeError, match="sem setup"):
        PhysicsOnlyTask().tick()


@pytest.fixture
async def host_factory() -> AsyncIterator[Callable[..., SimWorkerHost]]:
    hosts: list[SimWorkerHost] = []

    def make(mode: Literal["process", "thread"]) -> SimWorkerHost:
        host = SimWorkerHost(WorkerConfig(mode=mode, start_timeout_s=30.0), max_active_sessions=1)
        hosts.append(host)
        return host

    yield make
    for host in hosts:
        await host.stop()


async def _frames(handle: WorkerHandle, count: int, limit_s: float) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    async def run() -> None:
        async for raw in handle.outputs():
            item = orjson.loads(raw)
            if item["type"] == "telemetry.frame":
                items.append(item)
                if len(items) >= count:
                    return

    await asyncio.wait_for(run(), limit_s)
    return items


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_hosted_physics_frames(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode)
    await host.start()
    payload = orjson.dumps({"rpm": 3000.0, "noise": False})
    handle = await host.start_session("phys", TASK, payload, sim_hz=1000)
    frames = await _frames(handle, 25, 30.0)
    indexes = [f["payload"]["frame_index"] for f in frames]
    assert indexes == list(range(indexes[0], indexes[0] + len(indexes)))
    assert all(f["payload"]["rpm"] > 0 for f in frames)
    assert handle.stats.ticks >= 400
    await host.stop_session("phys")
    assert os.getpid() > 0


def test_worker_mode_default_fixed_by_benchmark() -> None:
    """T409: o benchmark D-04 com a física real fixou ``process`` como padrão."""
    from simremap.core.config import WORKER_MODE_DEFAULT, Settings

    assert WORKER_MODE_DEFAULT == "process"
    assert Settings.model_fields["worker_mode"].default == WORKER_MODE_DEFAULT
