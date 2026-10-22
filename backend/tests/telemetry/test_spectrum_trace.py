"""Espectro por frame, traço de pressão ≤ 10 Hz e ``stats`` (T170, T332; tel RF-20, RF-21,
RF-23; D-BUS-10; D-WS-08)."""

from __future__ import annotations

import math
from typing import Any, ClassVar

import numpy as np
import orjson
import pytest
from fastapi.testclient import TestClient
from tel_helpers import make_sampler_task, pump
from ws_helpers import is_error, is_frame, new_session, recv_until, send, url

from simremap.damage.config import DamageConfig
from simremap.damage.spectrum import SpectrumGenerator, floor_spectrum
from simremap.telemetry.broadcaster import (
    ClientSubscription,
    ConnectionQueue,
    FpsMeter,
    render_frame,
)
from simremap.telemetry.contracts import KnockSpectrum, PressureTrace, TelemetryFrame
from simremap.telemetry.spectrum import (
    DB_FLOOR,
    spectrum_payload,
    to_knock_spectrum,
    trace_every_n_frames,
    trace_payload,
    trace_to_contract,
)

BORE_HATCH = 82.5


def _generator(seed: int = 7) -> SpectrumGenerator:
    return SpectrumGenerator(BORE_HATCH, DamageConfig(), np.random.default_rng(seed))


def test_knock_peak_at_draper_resonance() -> None:
    gen = _generator()
    gen.observe(6.0)  # bar de MAPO (knock severo no cilindro 1)
    spectrum = to_knock_spectrum(gen.frame(1.0, 5000.0))
    assert len(spectrum.bins_hz) == len(spectrum.magnitude_db) == 256
    assert spectrum.bins_hz[1] - spectrum.bins_hz[0] == pytest.approx(78.125)
    assert spectrum.resonance_hz[0] == pytest.approx(6720, rel=0.02)  # Draper, B = 82,5 mm
    peak = spectrum.bins_hz[int(np.argmax(spectrum.magnitude_db))]
    assert abs(peak - spectrum.resonance_hz[0]) <= 160
    assert all(round(v, 1) == v for v in spectrum.magnitude_db)  # 1 casa decimal


def test_no_knock_stays_within_floor_plus_6db() -> None:
    gen = _generator(11)
    for i in range(20):
        frame = gen.frame(i * 0.02, 3000.0)
        floor_db = 10.0 * np.log10(floor_spectrum(3000.0, DamageConfig()))
        assert np.all(np.array(frame.magnitude_db) <= floor_db + 6.0)


def test_spectrum_payload_floor_and_shape_errors() -> None:
    class Frame:
        bins_hz: ClassVar[list[float]] = [0.0] * 256
        magnitude_db: ClassVar[list[float]] = [math.nan] + [-50.0] * 255
        resonance_hz: ClassVar[list[float]] = [1.0, 2.0, 3.0, 4.0]

    payload = spectrum_payload(Frame())
    assert payload["magnitude_db"][0] == DB_FLOOR and payload["sensor"] == "block"
    KnockSpectrum.model_validate(payload)

    class Short(Frame):
        bins_hz: ClassVar[list[float]] = [0.0] * 10

    with pytest.raises(ValueError, match="256"):
        spectrum_payload(Short())

    class NoModes(Frame):
        resonance_hz: ClassVar[list[float]] = [1.0]

    with pytest.raises(ValueError, match="ressonâncias"):
        spectrum_payload(NoModes())


def test_sampler_frames_with_damage_spectrum_source() -> None:
    task = make_sampler_task()
    sampler = task.session.sampler
    sampler.bind_spectrum(task.session.damage.spectrum_frame)  # type: ignore[attr-defined]
    task.handle_command({"type": "operator.throttle", "throttle_pct": 30.0})
    frames = [e for e in pump(task, None, 200) if e["type"] == "telemetry.frame"]
    assert frames
    for frame in frames:
        KnockSpectrum.model_validate(frame["payload"]["knock_spectrum"])

    def broken(t: float) -> Any:
        raise RuntimeError("falha")

    sampler.bind_spectrum(broken)  # type: ignore[attr-defined]
    frames = [e for e in pump(task, None, 100) if e["type"] == "telemetry.frame"]
    assert frames and all(f["payload"]["knock_spectrum"] is None for f in frames)


def test_pressure_trace_at_most_10hz_and_stats() -> None:
    task = make_sampler_task()
    task.handle_command({"type": "operator.throttle", "throttle_pct": 30.0})
    frames = [e for e in pump(task, None, 3000) if e["type"] == "telemetry.frame"]
    assert len(frames) >= 140
    queue = ConnectionQueue()
    meter = FpsMeter()
    sub = ClientSubscription(channels=("rpm",), trace_cylinder=2)
    rendered = []
    for i, raw in enumerate(frames):
        env = {**raw, "seq": i}
        if i % 10 == 5:
            queue.dropped_frames += 1  # descarte forçado entre frames
        rendered.append(render_frame(env, sub, queue, meter.tick(env["t_sim_s"]), 1.0))
    last_second = rendered[-50:]
    with_trace = [r for r in last_second if r["payload"]["cyl_pressure_trace"] is not None]
    assert 1 <= len(with_trace) <= 10
    for r in with_trace:
        trace = PressureTrace.model_validate(r["payload"]["cyl_pressure_trace"])
        assert trace.cylinder == 2 and len(trace.crank_deg) == len(trace.p_bar) > 10
        assert max(trace.p_bar) > 1.0
    for r in rendered:
        TelemetryFrame.model_validate(r["payload"])
        assert set(r["payload"]["channels"]) == {"rpm"}
    dropped = [r["payload"]["stats"]["dropped_frames"] for r in rendered]
    assert dropped == sorted(dropped) and dropped[-1] > 0
    assert rendered[-1]["payload"]["stats"]["fps_actual"] == 50.0
    assert rendered[-1]["payload"]["stats"]["real_time_factor"] == 1.0
    assert trace_every_n_frames(50) == 5 and trace_every_n_frames(60) == 6
    assert trace_every_n_frames(30) == 3


def test_trace_payload_helpers() -> None:
    raw = trace_payload(-20.4, [100.0, 250.0, math.nan])
    assert raw == {"crank_deg": [-21, -20, -19], "p_bar": [1.0, 2.5, 0.0]}
    assert trace_to_contract(3, raw).cylinder == 3


def test_e2e_pressure_trace_and_damage_spectrum(e2e_client: TestClient) -> None:
    """O laço liga ``damage.spectrum_frame`` ao amostrador: ``spectrum = true`` recebe o
    espectro (sem ``SPECTRUM_UNAVAILABLE``) e o traço chega a ≤ 10 Hz."""
    sid = new_session(e2e_client)
    with e2e_client.websocket_connect(url(sid)) as ws:
        ws.receive_json()
        send(ws, "control.throttle", throttle_pct=20)
        send(
            ws, "control.subscribe", channels=["rpm"], pressure_trace={"cylinder": 2}, spectrum=True
        )
        frames: list[dict[str, Any]] = []
        seen: list[dict[str, Any]] = []
        while len(frames) < 150:
            frame, before = recv_until(ws, is_frame)
            seen.extend(before)
            frames.append(frame)
    assert not [m for m in seen if is_error("SPECTRUM_UNAVAILABLE")(m)]
    tail = frames[-50:]
    for frame in tail:
        KnockSpectrum.model_validate(frame["payload"]["knock_spectrum"])
    traces = [f for f in tail if f["payload"]["cyl_pressure_trace"] is not None]
    assert 1 <= len(traces) <= 10
    assert all(f["payload"]["cyl_pressure_trace"]["cylinder"] == 2 for f in traces)
    size = max(len(orjson.dumps(f)) for f in tail)
    assert size < 8000


def test_sampler_configure_gates_spectrum_and_trace() -> None:
    """``telemetry.config`` com ``spectrum``/``pressure_trace`` = false: nada é calculado."""
    task = make_sampler_task()
    task.handle_command({"type": "operator.throttle", "throttle_pct": 30.0})
    task.handle_command({"type": "telemetry.config", "spectrum": False, "pressure_trace": False})
    frames = [e for e in pump(task, None, 600) if e["type"] == "telemetry.frame"]
    assert frames
    assert all(f["payload"]["knock_spectrum"] is None for f in frames)
    assert all("_traces" not in f["payload"] for f in frames)
    task.handle_command({"type": "telemetry.config", "spectrum": True, "pressure_trace": True})
    frames = [e for e in pump(task, None, 600) if e["type"] == "telemetry.frame"]
    assert all(f["payload"]["knock_spectrum"] is not None for f in frames[1:])
    assert any("_traces" in f["payload"] for f in frames)


def test_real_time_factor_from_event_loop_reaches_frames_and_log() -> None:
    task = make_sampler_task()
    task.handle_command({"type": "telemetry.config", "real_time_factor": 0.987})
    task.handle_command({"type": "operator.throttle", "throttle_pct": 10.0})
    frames = [e for e in pump(task, None, 200) if e["type"] == "telemetry.frame"]
    assert frames[-1]["payload"]["channels"]["real_time_factor"] == pytest.approx(0.987)
