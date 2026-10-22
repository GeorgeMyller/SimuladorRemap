"""Filas, logbridge e protocolo do worker (T231, T446; RF-12, RF-13; D-05)."""

from __future__ import annotations

import queue
import threading
from typing import Any

import orjson
import pytest

from simremap.core.worker import DATA_OUTPUT_TYPES, SimTask, WorkerConfig
from simremap.core.worker.logbridge import (
    LogRateLimiter,
    WorkerLogBridge,
    build_log_envelope,
    set_worker_log,
    worker_log,
)
from simremap.core.worker.loop import WorkerSpec, run_worker
from simremap.core.worker.protocol import STATS_SIZE, StatsSlot, WorkerState, resolve_task
from simremap.core.worker.queues import (
    CommandQueueFull,
    OutputRouter,
    WorkerChannels,
    classify_output,
    make_thread_channels,
    output_type,
    put_drop_oldest,
    submit_command,
)
from simremap.core.worker.synthetic import SyntheticTask


def env(kind: str, **extra: Any) -> bytes:
    return orjson.dumps({"v": 1, "type": kind, **extra})


def test_default_capacities() -> None:
    cfg = WorkerConfig()
    channels = make_thread_channels(cfg)
    assert (cfg.command_queue_size, cfg.critical_queue_size, cfg.output_queue_size) == (64, 64, 256)
    assert cfg.mode == "process" and cfg.start_method == "spawn"
    assert cfg.heartbeat_interval_s == 0.5 and cfg.heartbeat_timeout_s == 2.0
    assert cfg.stop_timeout_s == 5.0 and cfg.log_lines_per_s == 50
    assert isinstance(channels.commands, queue.Queue)


def test_classification_of_lanes() -> None:
    assert DATA_OUTPUT_TYPES == {"telemetry.frame", "event.knock", "log"}
    for kind in ("telemetry.frame", "event.knock", "log"):
        assert classify_output(env(kind)) == "data"
    for kind in ("run.state", "event.failure", "ack", "run.result", "datalog.closed", "x.y"):
        assert classify_output(env(kind)) == "critical"
    assert classify_output(b"nao json") == "critical"
    assert classify_output(b"[1, 2]") == "critical"
    big = orjson.dumps({"payload": "x" * 400, "type": "telemetry.frame"})
    assert output_type(big) == "telemetry.frame"  # "type" depois dos 256 bytes iniciais
    assert output_type(orjson.dumps({"type": 3})) is None


def test_command_queue_never_drops() -> None:
    q: queue.Queue[Any] = queue.Queue(maxsize=2)
    submit_command(q, {"type": "a"})
    submit_command(q, {"type": "b"})
    with pytest.raises(CommandQueueFull):
        submit_command(q, {"type": "c"})
    assert [q.get_nowait()["type"], q.get_nowait()["type"]] == ["a", "b"]


def test_put_drop_oldest() -> None:
    q: queue.Queue[int] = queue.Queue(maxsize=3)
    dropped = [put_drop_oldest(q, i) for i in range(6)]
    assert dropped == [False, False, False, True, True, True]
    assert [q.get_nowait() for _ in range(3)] == [3, 4, 5]


def test_put_drop_oldest_when_oldest_unavailable() -> None:
    class Stuck:
        def put_nowait(self, item: Any) -> None:
            raise queue.Full

        def get_nowait(self) -> Any:
            raise queue.Empty

        def get(self, block: bool = True, timeout: float | None = None) -> Any:
            raise queue.Empty

    assert put_drop_oldest(Stuck(), 1) is True


def _q(lane: object) -> queue.Queue[Any]:
    assert isinstance(lane, queue.Queue)
    return lane


def _router(
    critical: int = 2, data: int = 3, backlog: int = 4, gate: Any = None
) -> tuple[OutputRouter, WorkerChannels]:
    channels = WorkerChannels(
        commands=queue.Queue(maxsize=4),
        critical=queue.Queue(maxsize=critical),
        data=queue.Queue(maxsize=data),
    )
    return OutputRouter(channels, backlog, gate), channels


def test_router_data_lane_counts_drops() -> None:
    router, channels = _router()
    for i in range(5):
        router.route(env("telemetry.frame", i=i))
    assert router.dropped_outputs == 2
    got = [orjson.loads(channels.data.get_nowait())["i"] for _ in range(3)]
    assert got == [2, 3, 4]


def test_router_critical_backlog_preserves_order_and_overflow() -> None:
    router, channels = _router(critical=2, backlog=3)
    for i in range(4):
        router.route(env("run.state", i=i))
    assert router.telemetry_degraded
    assert router.critical_backlog == 2
    assert not router.overflowed
    assert orjson.loads(channels.critical.get_nowait())["i"] == 0
    router.route(env("ack", i=4))  # entra no fim do backlog e o flush avança
    assert router.critical_backlog == 2
    order = []
    while True:
        try:
            order.append(orjson.loads(channels.critical.get_nowait())["i"])
        except queue.Empty:
            router.flush_backlog()
            if router.critical_backlog == 0 and _q(channels.critical).empty():
                break
    assert order == [1, 2, 3, 4]
    for i in range(6):
        router.route(env("event.failure", i=i))
    assert router.overflowed


def test_router_log_gate() -> None:
    allowed = iter([True, False, True])
    router, channels = _router(data=8, gate=lambda: next(allowed))
    for _ in range(3):
        router.route(build_log_envelope("info", "x", {}))
    assert router.log_dropped == 1
    assert _q(channels.data).qsize() == 2
    router.set_log_gate(lambda: False)
    router.route(build_log_envelope("info", "x", {}))
    assert router.log_dropped == 2


def test_rate_limiter_window() -> None:
    now = [0.0]
    limiter = LogRateLimiter(2, clock=lambda: now[0])
    assert [limiter.allow() for _ in range(3)] == [True, True, False]
    now[0] = 1.0
    assert limiter.allow() is True


def test_log_envelope_and_bridge() -> None:
    envelope = orjson.loads(build_log_envelope("bogus", "e.x", {"n": 1}))
    assert envelope == {"v": 1, "type": "log", "level": "info", "event": "e.x", "fields": {"n": 1}}
    sent: list[bytes] = []
    bridge = WorkerLogBridge(sent.append)
    bridge.debug("a")
    bridge.info("b")
    bridge.warning("c")
    bridge.error("d", code="X")
    assert [orjson.loads(s)["level"] for s in sent] == ["debug", "info", "warning", "error"]
    assert worker_log() is not bridge  # ponte nula fora do worker
    worker_log().info("ignorado")
    set_worker_log(bridge)
    try:
        assert worker_log() is bridge
        seen: list[WorkerLogBridge] = []
        thread = threading.Thread(target=lambda: seen.append(worker_log()))
        thread.start()
        thread.join()
        assert seen[0] is not bridge  # ponte por thread (sessões em threads distintas)
    finally:
        set_worker_log(None)


def test_resolve_task_variants() -> None:
    task = resolve_task("simremap.core.worker.synthetic:SyntheticTask")
    assert isinstance(task, SimTask)
    assert isinstance(resolve_task(SyntheticTask), SyntheticTask)
    with pytest.raises(ValueError, match="modulo:Classe"):
        resolve_task("simremap.core.worker.synthetic")
    with pytest.raises(TypeError, match="chamável"):
        resolve_task("simremap.core.worker.protocol:COMMAND_STOP")
    with pytest.raises(TypeError, match="SimTask"):
        resolve_task("builtins:dict")


def test_worker_state_labels() -> None:
    assert WorkerState.CRITICAL_OVERFLOW.label == "critical_overflow"
    assert STATS_SIZE == len(StatsSlot)


def test_synthetic_task_is_deterministic() -> None:
    def run(n: int) -> list[bytes]:
        task = SyntheticTask()
        task.setup(orjson.dumps({"fps": 50, "knock_every": 7, "work_n": 4}))
        out = list(task.drain_outputs())
        for _ in range(n):
            task.tick()
            out.extend(task.drain_outputs())
        task.teardown()
        return [*out, *task.drain_outputs()]

    first, second = run(500), run(500)
    assert first == second
    frames = [orjson.loads(x) for x in first if b"telemetry.frame" in x]
    assert [f["payload"]["frame_index"] for f in frames] == list(range(26))  # 50 FPS
    task = SyntheticTask()
    with pytest.raises(ValueError, match="objeto JSON"):
        task.setup(b"[1]")
    task.setup(b"")
    task.handle_command({"type": "desconhecido"})
    task.handle_command({"type": "run.state", "state": "arming"})
    kinds = [orjson.loads(x)["type"] for x in task.drain_outputs()]
    assert kinds == ["run.state", "ack", "run.state"]


def test_run_worker_stop_command_and_critical_overflow() -> None:
    cfg = WorkerConfig(mode="thread", critical_queue_size=8, max_critical_backlog=4)
    channels = make_thread_channels(cfg)
    stats = [0.0] * STATS_SIZE
    stop = threading.Event()
    channels.commands.put_nowait({"type": "flood_critical", "count": 30})
    run_worker(WorkerSpec(SyntheticTask, b"", 1000), channels, stats, stop, cfg)
    assert WorkerState(int(stats[StatsSlot.STATE])) is WorkerState.CRITICAL_OVERFLOW
    assert stats[StatsSlot.TELEMETRY_DEGRADED] == 1.0

    channels = make_thread_channels(cfg)
    stats = [0.0] * STATS_SIZE
    channels.commands.put_nowait({"type": "echo"})
    channels.commands.put_nowait({"type": "stop"})
    run_worker(WorkerSpec(SyntheticTask, b"", 1000), channels, stats, stop, cfg)
    assert WorkerState(int(stats[StatsSlot.STATE])) is WorkerState.STOPPED
    assert stats[StatsSlot.TICKS] == 0  # stop processado antes do 1.º tick
    kinds = []
    while not _q(channels.critical).empty():
        kinds.append(orjson.loads(channels.critical.get_nowait())["type"])
    assert kinds == ["run.state", "ack", "run.state"]  # setup, echo, teardown


def test_run_worker_setup_failure_reports_detail() -> None:
    cfg = WorkerConfig(mode="thread")
    channels = make_thread_channels(cfg)
    stats = [0.0] * STATS_SIZE
    run_worker(
        WorkerSpec(SyntheticTask, orjson.dumps({"fail_setup": True}), 1000),
        channels,
        stats,
        threading.Event(),
        cfg,
    )
    assert WorkerState(int(stats[StatsSlot.STATE])) is WorkerState.SETUP_FAILED
    failure = orjson.loads(channels.critical.get_nowait())
    assert failure["type"] == "worker.setup_failed"
    assert "falha de setup" in failure["payload"]["detail"]


def test_run_worker_stop_event() -> None:
    cfg = WorkerConfig(mode="thread")
    channels = make_thread_channels(cfg)
    stats = [0.0] * STATS_SIZE
    stop = threading.Event()
    stop.set()
    run_worker(WorkerSpec(SyntheticTask, b"", 1000), channels, stats, stop, cfg)
    assert WorkerState(int(stats[StatsSlot.STATE])) is WorkerState.STOPPED
