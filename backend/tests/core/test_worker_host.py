"""``SimWorkerHost`` nos modos ``process`` e ``thread`` (T082; RF-11, RF-12; D-04, D-05).

Usa a ``SyntheticTask`` determinística (``simremap.core.worker.synthetic``).
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

import orjson
import pytest

from simremap.core.errors import SimRemapError
from simremap.core.worker.host import SimWorkerHost, WorkerHandle
from simremap.core.worker.protocol import WorkerConfig, WorkerState

TASK = "simremap.core.worker.synthetic:SyntheticTask"
LogEvents = Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]]


def _payload(**options: Any) -> bytes:
    return orjson.dumps(options)


async def _collect(
    handle: WorkerHandle,
    until: Callable[[list[dict[str, Any]]], bool],
    limit_s: float = 5.0,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    async def run() -> None:
        async for raw in handle.outputs():
            items.append(orjson.loads(raw))
            if until(items):
                return

    await asyncio.wait_for(run(), limit_s)
    return items


def _has(kind: str) -> Callable[[list[dict[str, Any]]], bool]:
    return lambda items: any(i["type"] == kind for i in items)


@pytest.fixture
async def host_factory() -> AsyncIterator[Callable[..., SimWorkerHost]]:
    hosts: list[SimWorkerHost] = []

    def make(
        mode: Literal["process", "thread"] = "thread", sessions: int = 1, **config: Any
    ) -> SimWorkerHost:
        host = SimWorkerHost(WorkerConfig(mode=mode, **config), max_active_sessions=sessions)
        hosts.append(host)
        return host

    yield make
    for host in hosts:
        await host.stop()


# --------------------------------------------------------------------------- ambos os modos


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_isolation_tick_off_event_loop(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode)
    await host.start()
    handle = await host.start_session("s1", TASK, _payload(report_thread=True), sim_hz=1000)
    items = await _collect(handle, _has("task.info"))
    info = next(i for i in items if i["type"] == "task.info")["payload"]
    if mode == "thread":
        assert info["tick_thread"] != threading.get_ident()
        assert info["pid"] == os.getpid()
    else:
        assert info["pid"] != os.getpid()
        assert info["fastapi_loaded"] is False  # o worker nunca importa fastapi
        assert info["sqlalchemy_loaded"] is False  # nem toca no banco
        assert info["omp_threads"] == "1"
        assert info["openblas_threads"] == "1"
    assert handle.mode == mode
    await host.stop_session("s1")
    assert host.active_sessions == 0
    if mode == "process":
        assert multiprocessing.active_children() == []


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_commands_and_frames_at_50fps(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode)
    await host.start()
    handle = await host.start_session("s1", TASK, _payload(fps=50), sim_hz=1000)
    await handle.send({"type": "echo", "value": 7})
    items = await _collect(handle, lambda xs: sum(x["type"] == "telemetry.frame" for x in xs) >= 25)
    ack = next(i for i in items if i["type"] == "ack")
    assert ack["payload"] == {"command": "echo", "value": 7}
    frames = [i["payload"]["frame_index"] for i in items if i["type"] == "telemetry.frame"]
    assert frames == list(range(frames[0], frames[0] + len(frames)))
    stats = handle.stats
    assert stats.ticks >= 400
    assert stats.state == "running"
    assert stats.dropped_outputs == 0
    await host.stop_session("s1")
    assert handle.state == "stopped"


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_command_queue_full_returns_sim_worker_busy(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode, command_queue_size=8)
    await host.start()
    handle = await host.start_session("s1", TASK, b"")
    await handle.send({"type": "hang", "seconds": 1.5})
    await asyncio.sleep(0.2)  # o worker está bloqueado no tick: a fila não é drenada
    sent = 0
    loop_t0 = time.perf_counter()
    with pytest.raises(SimRemapError) as info:
        for _ in range(100):
            await handle.send({"type": "echo", "value": sent})
            sent += 1
    assert (time.perf_counter() - loop_t0) < 0.5  # nunca bloqueia o event loop
    assert info.value.error_code == "SIM_WORKER_BUSY"
    assert info.value.error_status == 503
    assert info.value.headers == {"Retry-After": "1"}
    assert sent == 8
    await host.stop_session("s1")


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_data_lane_drops_oldest_and_keeps_rate(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode, output_queue_size=16)
    await host.start()
    handle = await host.start_session("s1", TASK, _payload(fps=50, knock_every=5), sim_hz=1000)
    await asyncio.sleep(2.2)  # consumidor parado
    stats = handle.stats
    assert stats.dropped_outputs > 300
    assert stats.achieved_hz >= 0.97 * 1000
    items = await _collect(handle, lambda xs: sum(x["type"] == "telemetry.frame" for x in xs) >= 3)
    first_frame = next(i for i in items if i["type"] == "telemetry.frame")
    # O mais antigo foi descartado: o 1.º frame lido é recente (≤ 16 itens atrás).
    assert first_frame["t_sim_s"] > 1.5
    await host.stop_session("s1")


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_critical_lane_never_drops(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode, critical_queue_size=8, output_queue_size=16)
    await host.start()
    handle = await host.start_session("s1", TASK, _payload(fps=50))
    await handle.send({"type": "flood_critical", "count": 40})
    await asyncio.sleep(0.6)  # faixa crítica cheia: backlog local no worker
    stats = handle.stats
    assert stats.telemetry_degraded is True
    assert stats.critical_backlog > 0
    acks = await _collect(handle, lambda xs: sum(x["type"] == "ack" for x in xs) >= 40, limit_s=10)
    indices = [a["payload"]["index"] for a in acks if a["type"] == "ack"]
    assert indices == list(range(40))  # nenhum perdido, ordem preservada
    await asyncio.sleep(0.1)
    assert handle.stats.critical_backlog == 0
    await host.stop_session("s1")


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_task_exception_emits_worker_crashed(
    mode: Literal["process", "thread"],
    host_factory: Callable[..., SimWorkerHost],
    caplog: pytest.LogCaptureFixture,
    log_events: LogEvents,
) -> None:
    host = host_factory(mode)
    await host.start()
    handle = await host.start_session("s1", TASK, b"")
    await handle.send({"type": "crash"})
    items = await _collect(handle, _has("worker.crashed"))
    crashed = next(i for i in items if i["type"] == "worker.crashed")
    assert crashed["payload"]["code"] == "SIM_WORKER_UNAVAILABLE"
    assert crashed["payload"]["reason"] == "task_exception"
    assert handle.state == "crashed"
    with pytest.raises(SimRemapError) as info:
        await handle.send({"type": "echo"})
    assert info.value.error_code == "SIM_WORKER_UNAVAILABLE"
    assert host.health()["status"] == "down"
    events = [e["event"] for e in log_events(caplog)]
    assert "worker.crashed" in events
    await host.stop_session("s1")
    assert host.health()["status"] == "ok"


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_heartbeat_timeout_marks_crashed(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode, heartbeat_timeout_s=0.6, stop_timeout_s=1.0)
    await host.start()
    handle = await host.start_session("s1", TASK, b"")
    assert host.health()["status"] == "ok"
    await handle.send({"type": "hang", "seconds": 1.6})
    t0 = time.monotonic()
    items = await _collect(handle, _has("worker.crashed"), limit_s=5)
    elapsed = time.monotonic() - t0
    crashed = next(i for i in items if i["type"] == "worker.crashed")
    assert crashed["payload"]["reason"] == "heartbeat_timeout"
    assert 0.5 <= elapsed <= 1.5
    assert not handle.is_healthy()
    await host.stop_session("s1")


# --------------------------------------------------------------------------- modo process


async def test_process_killed_is_detected(host_factory: Callable[..., SimWorkerHost]) -> None:
    host = host_factory("process")
    await host.start()
    handle = await host.start_session("s1", TASK, b"")
    pid = handle.backend.pid  # type: ignore[attr-defined]
    assert isinstance(pid, int)
    os.kill(pid, 9)
    items = await _collect(handle, _has("worker.crashed"))
    assert items[-1]["payload"]["reason"] == "worker_exited"
    await host.stop_session("s1")


async def test_process_mode_requires_importable_task(
    host_factory: Callable[..., SimWorkerHost],
) -> None:
    from simremap.core.worker.synthetic import SyntheticTask

    host = host_factory("process")
    with pytest.raises(TypeError, match="modulo:Classe"):
        await host.start_session("s1", SyntheticTask, b"")
    assert host.active_sessions == 0


# --------------------------------------------------------------------------- arranque e capacidade


@pytest.mark.parametrize("mode", ["thread", "process"])
async def test_setup_failure_is_sim_worker_unavailable(
    mode: Literal["process", "thread"], host_factory: Callable[..., SimWorkerHost]
) -> None:
    host = host_factory(mode)
    with pytest.raises(SimRemapError) as info:
        await host.start_session("s1", TASK, _payload(fail_setup=True))
    assert info.value.error_code == "SIM_WORKER_UNAVAILABLE"
    assert host.active_sessions == 0


async def test_start_timeout(host_factory: Callable[..., SimWorkerHost]) -> None:
    host = host_factory("thread", start_timeout_s=0.2)

    class SlowSetup:
        def setup(self, init_payload: bytes) -> None:
            time.sleep(0.6)

        def handle_command(self, command: dict[str, object]) -> None: ...
        def tick(self) -> None: ...
        def drain_outputs(self) -> list[bytes]:
            return []

        def teardown(self) -> None: ...

    with pytest.raises(SimRemapError, match="não arrancou"):
        await host.start_session("s1", SlowSetup, b"")
    assert host.active_sessions == 0


async def test_capacity_and_duplicates(host_factory: Callable[..., SimWorkerHost]) -> None:
    host = host_factory("thread", sessions=1)
    await host.start_session("s1", TASK, b"")
    with pytest.raises(SimRemapError) as info:
        await host.start_session("s2", TASK, b"")
    assert info.value.error_code == "SIM_CAPACITY_EXCEEDED"
    assert info.value.error_status == 409
    two = host_factory("thread", sessions=2)
    await two.start_session("a", TASK, b"")
    with pytest.raises(SimRemapError) as dup:
        await two.start_session("a", TASK, b"")
    assert dup.value.error_code == "CONFLICT"
    await two.start_session("b", TASK, b"")
    assert sorted(two.sessions()) == ["a", "b"]
    assert two.find("zzz") is None
    with pytest.raises(SimRemapError) as missing:
        two.get("zzz")
    assert missing.value.error_code == "RESOURCE_NOT_FOUND"
    assert two.get("a").session_id == "a"


async def test_invalid_inputs(host_factory: Callable[..., SimWorkerHost]) -> None:
    host = host_factory("thread")
    with pytest.raises(ValueError, match="sim_hz"):
        await host.start_session("s1", TASK, b"", sim_hz=50)
    handle = await host.start_session("s1", TASK, b"")
    with pytest.raises(ValueError, match="type"):
        await handle.send({"value": 1})
    with pytest.raises(ValueError, match="stop"):
        await handle.send({"type": "stop"})


# --------------------------------------------------------------------------- logs e overrun


async def test_worker_logs_are_reemitted_with_rate_limit(
    settings_factory: Any,
    host_factory: Callable[..., SimWorkerHost],
    caplog: pytest.LogCaptureFixture,
    log_events: LogEvents,
) -> None:
    caplog.set_level("INFO")
    host = host_factory("thread", log_lines_per_s=50)
    await host.start()
    handle = await host.start_session("s-log", TASK, _payload(fps=50))
    await handle.send({"type": "log_burst", "count": 120})
    await _collect(handle, lambda xs: sum(x["type"] == "telemetry.frame" for x in xs) >= 10)
    reemitted = [e for e in log_events(caplog) if e["event"] == "synthetic.log"]
    assert len(reemitted) == 50
    assert all(e["session_id"] == "s-log" and e["source"] == "worker" for e in reemitted)
    assert handle.stats.log_dropped == 70


async def test_overrun_event_logged(
    host_factory: Callable[..., SimWorkerHost],
    caplog: pytest.LogCaptureFixture,
    log_events: LogEvents,
) -> None:
    caplog.set_level("INFO")
    host = host_factory("thread", overrun_window_s=0.3)
    await host.start()

    class SlowTick:
        def setup(self, init_payload: bytes) -> None: ...
        def handle_command(self, command: dict[str, object]) -> None: ...
        def tick(self) -> None:
            time.sleep(0.004)

        def drain_outputs(self) -> list[bytes]:
            return []

        def teardown(self) -> None: ...

    handle = await host.start_session("s-slow", SlowTick, b"", sim_hz=1000)
    await asyncio.sleep(1.3)
    overruns = [e for e in log_events(caplog) if e["event"] == "worker.overrun"]
    assert 1 <= len(overruns) <= 2  # no máximo 1 por segundo
    event = overruns[0]
    assert event["session_id"] == "s-slow"
    assert event["overrun_ticks"] > 0
    assert 0 < event["real_time_factor"] < 0.5
    assert handle.stats.overrun_ticks > 100
    assert handle.real_time_factor < 0.5


async def test_wall_budget_ticks_exempts_accelerated_ticks_from_overrun(
    host_factory: Callable[..., SimWorkerHost],
) -> None:
    """T031: tick acelerado (``wall_budget_ticks`` = 10) de 4 ms não conta overrun."""
    host = host_factory("thread", overrun_window_s=0.3)
    await host.start()

    class AcceleratedTick:
        wall_budget_ticks = 10

        def setup(self, init_payload: bytes) -> None: ...
        def handle_command(self, command: dict[str, object]) -> None: ...
        def tick(self) -> None:
            time.sleep(0.004)

        def drain_outputs(self) -> list[bytes]:
            return []

        def teardown(self) -> None: ...

    handle = await host.start_session("s-fast-forward", AcceleratedTick, b"", sim_hz=1000)
    await asyncio.sleep(0.6)
    assert handle.stats.ticks > 50
    assert handle.stats.overrun_ticks == 0


async def test_teardown_failure_is_logged_not_fatal(
    host_factory: Callable[..., SimWorkerHost],
) -> None:
    host = host_factory("thread")
    handle = await host.start_session("s1", TASK, b"")
    await handle.send({"type": "fail_teardown"})
    await asyncio.sleep(0.05)
    await host.stop_session("s1")
    assert handle.worker_state is WorkerState.STOPPED
    assert handle.failed is False


async def test_host_stop_leaves_no_workers(host_factory: Callable[..., SimWorkerHost]) -> None:
    host = SimWorkerHost(WorkerConfig(mode="thread"), max_active_sessions=2)
    await host.start()
    first = await host.start_session("a", TASK, b"")
    await host.start_session("b", TASK, b"")
    stream = first.outputs()
    assert await stream.__anext__()  # leitor ativo
    await host.stop()
    assert host.active_sessions == 0
    assert not host.running
    remaining = [item async for item in stream]
    assert all(orjson.loads(r)["type"] != "worker.crashed" for r in remaining)
    await asyncio.sleep(0.2)
    alive = [t.name for t in threading.enumerate() if t.name.startswith("simworker")]
    assert alive == []
    await first.stop()  # idempotente


async def test_from_settings(settings_factory: Any) -> None:
    host = SimWorkerHost.from_settings(settings_factory(max_active_sessions=2, sim_hz=500))
    assert host.mode == "thread"
    assert host.max_active_sessions == 2
    assert host.default_sim_hz == 500
