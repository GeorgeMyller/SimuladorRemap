"""Ponto de assinatura (``dyno.stream``), amostrador de frames e transporte do traço do dano."""

from __future__ import annotations

import asyncio

import numpy as np
import orjson
import pytest
from dyno_helpers import drain, make_task

from simremap.damage.trace import DamageTraceSnapshot
from simremap.dyno.sampler import FrameSampler, load_sampler
from simremap.dyno.stream import EVENT_QUEUE_SIZE, FRAME_QUEUE_SIZE, SessionStream, StreamHub
from simremap.dyno.trace_codec import decode_trace, encode_trace


def env(kind: str, t: float = 0.0, **payload: object) -> bytes:
    return orjson.dumps({"v": 1, "type": kind, "t_sim_s": t, "payload": payload})


async def test_seq_is_shared_monotonic_and_internal_types_are_hidden() -> None:
    stream = SessionStream("s1")
    out = [
        stream.publish(env("telemetry.frame", 0.02, frame_index=1)),
        stream.publish(env("ack", 0.02)),
        stream.publish(env("run.state", 0.03, state="arming")),
        stream.publish({"type": "error", "t_sim_s": 0.03, "payload": {"code": "X"}}),
    ]
    assert out[1] is None
    assert [o["seq"] for o in out if o is not None] == [0, 1, 2]
    assert stream.last_run_state is not None and stream.last_run_state["seq"] == 1
    assert [e["seq"] for e in stream.events_after(0)] == [1, 2]
    async with stream.subscribe() as sub:
        assert stream.subscribers == 1
        stream.publish(env("event.failure", 1.0, mode="rod_failure"))
        got = await asyncio.wait_for(sub.__anext__(), 1.0)
        assert got["type"] == "event.failure" and got["seq"] == 3
    assert stream.subscribers == 0


async def test_backpressure_drops_old_frames_and_knock_only() -> None:
    stream = SessionStream("s1")
    async with stream.subscribe() as sub:
        for i in range(FRAME_QUEUE_SIZE + 5):
            stream.publish(env("telemetry.frame", i / 50, frame_index=i))
        for _ in range(EVENT_QUEUE_SIZE):
            stream.publish(env("event.knock", 1.0))
        stream.publish(env("run.state", 2.0, state="running"))
        assert sub.dropped_frames == 5
        assert sub.dropped_events == 1
        assert sub.events[-1]["type"] == "run.state"
        assert len(sub.frames) == FRAME_QUEUE_SIZE
        first = sub.get_nowait()  # ordem do seq: o frame mais antigo que sobrou vem antes
        assert first is not None and first["type"] == "telemetry.frame" and first["seq"] == 5
        stream.close()
        drained = [e async for e in sub]
        assert [e["seq"] for e in drained] == sorted(e["seq"] for e in drained)
        assert drained[-1]["type"] == "run.state"
        assert sub.get_nowait() is None
    assert stream.publish(env("run.state")) is None  # sessão fechada


async def test_hub_create_get_close() -> None:
    hub = StreamHub()
    stream = hub.create("a")
    assert hub.get("a") is stream
    async with stream.subscribe() as sub:
        hub.close("a")
        assert hub.get("a") is None
        assert [e async for e in sub] == []
    hub.create("b")
    hub.close_all()
    assert hub.get("b") is None
    async with stream.subscribe() as late:
        assert late.closed


def test_frame_sampler_boundaries_fps_and_channels() -> None:
    task = make_task()
    sampler = task.session.sampler
    assert isinstance(sampler, FrameSampler)
    for _ in range(100):
        task.step()
    frames = [e for e in drain(task) if e["type"] == "telemetry.frame"]
    assert len(frames) == 4  # 50 FPS a 1000 Hz: fecha 1 frame a cada 20 ticks
    payload = frames[-1]["payload"]
    assert payload["window_ticks"] == 20
    channels = payload["channels"]
    for name in ("rpm", "map_kpa", "lambda", "torque_nm", "power_kw", "egt_c", "health_min_pct"):
        assert name in channels
    assert channels["fuel_cut"] in (0.0, 1.0)
    sampler.set_fps(60)
    for _ in range(200):
        task.step()
    frames = [e for e in drain(task) if e["type"] == "telemetry.frame"]
    assert len(frames) == pytest.approx(12, abs=1)
    sampler.set_fps(5)  # limitado a 30
    assert sampler._pending_fps == 30


def test_load_sampler_spec() -> None:
    default = load_sampler(None, session_id="s", sim_hz=1000, fps=50, n_cyl=4, afr_stoich=14.7)
    assert isinstance(default, FrameSampler)
    custom = load_sampler(
        "simremap.dyno.sampler:FrameSampler",
        session_id="s",
        sim_hz=1000,
        fps=50,
        n_cyl=4,
        afr_stoich=14.7,
    )
    assert isinstance(custom, FrameSampler)
    with pytest.raises(TypeError):
        load_sampler(
            "simremap.dyno.stream:StreamHub",
            session_id="s",
            sim_hz=1000,
            fps=50,
            n_cyl=4,
            afr_stoich=14.7,
        )


def test_trace_codec_roundtrip_is_exact() -> None:
    task = make_task()
    for _ in range(300):
        task.step()
    trace = task.session.damage.freeze_trace()
    raw = orjson.loads(orjson.dumps(encode_trace(trace)))
    back = decode_trace(raw)
    assert isinstance(back, DamageTraceSnapshot)
    assert back.meta == trace.meta
    assert back.tick.keys() == trace.tick.keys()
    for name, array in trace.tick.items():
        np.testing.assert_array_equal(back.tick[name], array)
        assert not back.tick[name].flags.writeable
    for name, array in trace.cycle.items():
        np.testing.assert_array_equal(back.cycle[name], array)
    assert back.components == trace.components
    assert back.failures == trace.failures
    assert back.t_end_s == trace.t_end_s and back.extra == trace.extra


async def test_subscription_delivers_in_seq_order_across_queues() -> None:
    """Eventos não ultrapassam frames já enfileirados (o cliente descarta ``seq`` antigos)."""
    stream = SessionStream("s")
    async with stream.subscribe() as sub:
        for kind in ("telemetry.frame", "telemetry.frame", "run.state", "telemetry.frame"):
            stream.publish({"type": kind, "t_sim_s": 0.0, "payload": {}})
        stream.publish({"type": "event.knock", "t_sim_s": 0.0, "payload": {}})
        got = [sub.get_nowait() for _ in range(4)]
        last = await sub.__anext__()
        assert sub.get_nowait() is None
    seqs = [e["seq"] for e in got if e is not None] + [last["seq"]]
    assert seqs == [0, 1, 2, 3, 4]


def test_hub_stream_factory_extension_point() -> None:
    class Custom(SessionStream):
        pass

    hub = StreamHub()
    assert type(hub.create("a")) is SessionStream
    hub.set_stream_factory(Custom)
    assert type(hub.create("b")) is Custom
    hub.set_stream_factory(None)
    assert type(hub.create("c")) is SessionStream
    bad = StreamHub(lambda sid: object())  # type: ignore[arg-type, return-value]
    with pytest.raises(TypeError):
        bad.create("d")
