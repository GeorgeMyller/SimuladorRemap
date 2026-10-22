"""Auxiliares dos testes do telemetry-datalogger (importados por ``sys.path`` no conftest).

- ``make_sampler_task``: ``DynoSimTask`` real (hatch calibrado da fixture da física) com o
  ``TelemetrySampler`` instalado pelo campo ``sampler`` do ``DynoInitPayload``.
- ``pump``: avança a tarefa e publica cada saída num ``TelemetryStream`` (como o
  ``OutputRouter`` do dyno-bench faz no event loop).
- ``capture_record``: um ``TickRecord`` real (para alimentar o amostrador sem o laço).
- ``StubService``: o mínimo do ``TelemetryService`` usado por ``TelemetryConnection``.
- ``FakeWebSocket``: socket em memória (envio pode ser pausado para simular cliente parado).
- ``make_e2e_app``: app completa (``create_app``) com o dyno de teste e worker ``process``.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import orjson

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dyno"))

from dyno_helpers import (  # noqa: E402
    MECHANICAL_DAMAGE,
    FixtureCalibrationSource,
    make_dyno_app,
    make_task,
    start_run,
)

from simremap.dyno.runner import DynoSimTask  # noqa: E402
from simremap.dyno.sampler import TickRecord  # noqa: E402
from simremap.telemetry.broadcaster import TelemetryStream  # noqa: E402
from simremap.telemetry.channels import ChannelCatalog, build_catalog  # noqa: E402
from simremap.telemetry.sampler import SAMPLER_SPEC, TelemetrySampler  # noqa: E402

__all__ = [
    "MECHANICAL_DAMAGE",
    "SAMPLER_SPEC",
    "FakeWebSocket",
    "StubService",
    "capture_record",
    "make_e2e_app",
    "make_sampler_task",
    "pump",
    "records",
    "start_run",
]

SHORT_SWEEP = {"run_type": "sweep_pull", "end_rpm": 3000, "ramp_rate_rpm_s": 1000}


def make_sampler_task(**over: Any) -> DynoSimTask:
    over.setdefault("sampler", SAMPLER_SPEC)
    return make_task(**over)


def pump(
    task: DynoSimTask,
    stream: TelemetryStream | None,
    steps: int,
    *,
    until: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Avança ``steps`` passos (ou até ``until``) e publica as saídas no ``stream``."""
    published: list[dict[str, Any]] = []
    for _ in range(steps):
        task.step()
        stop = False
        for raw in task.drain_outputs():
            env = orjson.loads(raw)
            if stream is not None:
                out = stream.publish(raw)
                published.append(out if out is not None else env)
            else:
                published.append(env)
            if until is not None and until(env):
                stop = True
        if stop:
            break
    return published


def capture_record(task: DynoSimTask | None = None, warm_steps: int = 50) -> TickRecord:
    """Um ``TickRecord`` real do laço (o amostrador da tarefa é trocado por um gravador)."""
    task = task or make_task()
    captured: list[TickRecord] = []

    class _Grab:
        def on_tick(self, rec: TickRecord) -> None:
            captured.append(rec)

        def set_fps(self, fps: int) -> None:
            del fps

        def drain(self) -> list[bytes]:
            return []

    task.session.sampler = _Grab()
    task.handle_command({"type": "operator.throttle", "throttle_pct": 20.0})
    for _ in range(warm_steps):
        task.step()
    return captured[-1]


def records(
    base: TickRecord, n: int, *, start_tick: int = 0, run_id: str | None = None
) -> list[TickRecord]:
    """``n`` cópias do registo com ``tick``/``t_sim_s`` sequenciais."""
    sim_hz = 1000
    return [
        replace(base, tick=start_tick + i, t_sim_s=(start_tick + i) / sim_hz, run_id=run_id)
        for i in range(n)
    ]


def drained(sampler: TelemetrySampler) -> list[dict[str, Any]]:
    return [orjson.loads(raw) for raw in sampler.drain()]


class StubService:
    """``TelemetryService`` mínimo para ``TelemetryConnection`` sem dyno."""

    def __init__(self, catalog: ChannelCatalog | None = None) -> None:
        self._catalog = catalog or build_catalog(4, True)
        self.fps_calls: list[int] = []
        self.throttle_calls: list[float] = []
        self.composites: dict[int, tuple[bool, bool]] = {}
        self.active = False

    def catalog(self, session_id: str) -> ChannelCatalog:
        return self._catalog

    def runtime(self, session_id: str) -> None:
        return None

    def realtime_factor(self, session_id: str) -> float | None:
        return 1.0

    async def set_fps(self, session_id: str, fps: int) -> None:
        self.fps_calls.append(fps)

    def spectrum_available(self, session_id: str) -> bool:
        return True

    async def set_composites(
        self, session_id: str, connection_id: int, *, spectrum: bool, pressure_trace: bool
    ) -> None:
        self.composites[connection_id] = (spectrum, pressure_trace)

    async def release_composites(self, session_id: str, connection_id: int) -> None:
        self.composites.pop(connection_id, None)

    async def throttle(self, session_id: str, pct: float) -> str | None:
        if self.active:
            return "THROTTLE_LOCKED_BY_RUN"
        self.throttle_calls.append(pct)
        return None


class FakeWebSocket:
    """WebSocket em memória para ``TelemetryConnection`` (``paused`` bloqueia o envio)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.paused = asyncio.Event()
        self.paused.set()
        self.closed: tuple[int, str] | None = None
        self.accepted = False
        self.application_state = 1
        self.sent_bytes = 0
        self.headers: dict[str, str] = {}

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        await self.paused.wait()
        self.sent_bytes += len(text.encode())
        self.sent.append(orjson.loads(text))

    async def receive(self) -> dict[str, Any]:
        return await self.incoming.get()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)
        await self.incoming.put({"type": "websocket.disconnect", "code": code})

    def push(self, message: dict[str, Any] | str) -> None:
        text = message if isinstance(message, str) else orjson.dumps(message).decode()
        self.incoming.put_nowait({"type": "websocket.receive", "text": text})


def make_e2e_app(settings: Any, **task_options: Any) -> Any:
    """App completa com o dyno de teste (worker ``process``) e opções extra do laço."""
    app = make_dyno_app(settings, FixtureCalibrationSource())
    app.state.dyno_task_options.update(task_options)
    return app


def frame_envelope(seq: int, frame_index: int, t: float, **channels: float) -> dict[str, Any]:
    return {
        "type": "telemetry.frame",
        "seq": seq,
        "t_sim_s": t,
        "payload": {
            "session_id": "s",
            "run_id": None,
            "frame_index": frame_index,
            "window_ticks": 20,
            "channels": channels,
            "knock_spectrum": None,
            "cyl_pressure_trace": None,
            "stats": {
                "fps_actual": 50.0,
                "dropped_frames": 0,
                "dropped_events": 0,
                "real_time_factor": None,
                "tick": frame_index * 20,
            },
        },
    }


def raw_frame(frame_index: int, t: float, **channels: float) -> dict[str, Any]:
    env = frame_envelope(0, frame_index, t, **channels)
    env.pop("seq")
    return env


def raw_event(type_: str, t: float, **payload: Any) -> dict[str, Any]:
    return {"type": type_, "t_sim_s": t, "payload": payload}


def make_log(
    run_id: str,
    *,
    n: int = 15_000,
    torque_offset: float = 0.0,
    vehicle_id: str = "hatch-20t-gdi",
    rpm_range: tuple[float, float] = (2000.0, 6000.0),
    phase: str = "pull",
    seed: int = 7,
) -> Any:
    """``LogData`` sintético (catálogo do hatch) com rampa de RPM e eventos de puxada."""
    import numpy as np

    from simremap.telemetry.contracts import DataLogHeader, LogEvent, PullSegment
    from simremap.telemetry.datalog import LogData

    catalog = build_catalog(4, True)
    rpm = np.linspace(rpm_range[0], rpm_range[1], n)
    cols = np.full((len(catalog), n), np.nan, dtype=np.float64)
    values = {
        "rpm": rpm,
        "torque_nm": 300.0 + torque_offset + 0.01 * (rpm - 2000.0),
        "power_kw": rpm * 0.03,
        "whp": rpm * 0.035,
        "lambda": np.full(n, 0.85),
        "egt_c": 700.0 + rpm * 0.03,
        "fuel_cut": (np.arange(n) % 100 == 0).astype(float),
    }
    for k in range(1, 5):
        values[f"knock_intensity_cyl{k}"] = np.full(n, 0.05 * k)
    for name, col in values.items():
        cols[catalog.index[name]] = col
    header = DataLogHeader(
        run_id=run_id,
        session_id="0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c",
        vehicle_id=vehicle_id,
        profile_id="oem-stage",
        calibration_hash="b" * 64,
        fuel_id="e27",
        seed=seed,
        sim_hz=1000,
        start_tick=3000,
        n_samples=n,
        channels=list(catalog.channels),
        pulls=[PullSegment(pull_index=1, start_index=0, end_index=n, state="completed")],
        events=[
            LogEvent(index=0, type="run.state", payload={"state": "running", "phase": phase}),
            LogEvent(
                index=n - 1, type="run.state", payload={"state": "completed", "phase": "done"}
            ),
        ],
        terminal_state="completed",
    )
    t = (3000 + np.arange(n)) / 1000.0
    return LogData.build(header, t, cols.astype(np.float32))
