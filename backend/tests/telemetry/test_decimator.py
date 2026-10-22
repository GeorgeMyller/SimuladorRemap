"""Decimação e agregação (T162, T331; tel RF-05, RF-06; websocket-telemetry 2.2)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from simremap.telemetry.broadcaster import ClientSubscription, apply_subscribe
from simremap.telemetry.channels import AGG_CODES, build_catalog
from simremap.telemetry.contracts import Aggregation
from simremap.telemetry.decimator import FrameDecimator


def _agg(*codes: Aggregation) -> np.ndarray:
    return np.array([AGG_CODES[c] for c in codes], dtype=np.int8)


def _run(sim_hz: int, fps: int, seconds: float, start_tick: int = 0) -> list[int]:
    dec = FrameDecimator(sim_hz, fps, _agg(Aggregation.LAST))
    windows = []
    for k in range(start_tick, start_tick + round(seconds * sim_hz)):
        frame = dec.push(k, k / sim_hz, [float(k)])
        if frame is not None:
            assert frame.frame_index == (k * fps) // sim_hz
            assert frame.values[0] == k  # last
            windows.append(frame.window_ticks)
    return windows


def test_1000hz_50fps_60s_gives_3000_frames() -> None:
    windows = _run(1000, 50, 60.0)
    assert abs(len(windows) - 3000) <= 1
    assert set(windows) == {20}


def test_300hz_60fps_aggregates_5_ticks() -> None:
    windows = _run(300, 60, 2.0)
    assert set(windows) == {5} and len(windows) == 120


def test_non_integer_ratio_alternates_16_and_17_without_drift() -> None:
    windows = _run(1000, 60, 10.0)
    assert set(windows) == {16, 17}
    assert abs(len(windows) - 600) <= 1
    assert 10_000 - 17 <= sum(windows) <= 10_000  # sem ticks perdidos nem repetidos


def test_frame_index_from_session_tick_after_warmup() -> None:
    dec = FrameDecimator(1000, 50, _agg(Aggregation.LAST))
    frames = [dec.push(k, k / 1000, [0.0]) for k in range(3000, 3100)]
    closed = [f for f in frames if f is not None]
    assert [f.frame_index for f in closed] == [150, 151, 152, 153, 154]


def test_rf06_window_aggregations() -> None:
    codes = _agg(
        Aggregation.MAX, Aggregation.LAST, Aggregation.ANY, Aggregation.MIN, Aggregation.SUM
    )
    dec = FrameDecimator(1000, 50, codes)
    frame = None
    for i in range(20):
        knock = 0.8 if i == 7 else 0.0
        rpm = 3000.0 + i
        fuel_cut = 1.0 if i == 3 else 0.0
        health = 100.0 - (5.0 if i == 11 else 0.0)
        pops = 1.0 if i in (2, 5, 9) else 0.0
        frame = dec.push(i, i / 1000, [knock, rpm, fuel_cut, health, pops])
    assert frame is not None and frame.window_ticks == 20
    knock, rpm, fuel_cut, health, pops = frame.values.tolist()
    assert knock == pytest.approx(0.8)
    assert rpm == 3019.0  # valor do 20.º tick
    assert fuel_cut == 1.0
    assert health == 95.0
    assert pops == 3.0


def test_nan_is_ignored_by_extremes_and_all_nan_stays_nan() -> None:
    dec = FrameDecimator(1000, 50, _agg(Aggregation.MAX, Aggregation.MIN, Aggregation.LAST))
    frame = None
    for i in range(20):
        value = math.nan if i % 2 else float(i)
        frame = dec.push(i, i / 1000, [value, math.nan, value])
    assert frame is not None
    assert frame.values[0] == 18.0
    assert math.isnan(frame.values[1])
    assert math.isnan(frame.values[2])  # last = NaN (null no frame)


def test_fps_change_applies_on_next_boundary_and_keeps_index_contiguous() -> None:
    dec = FrameDecimator(1000, 50, _agg(Aggregation.LAST))
    indices: list[int] = []
    windows: list[int] = []
    for k in range(0, 2000):
        if k == 510:
            dec.set_fps(60)
        frame = dec.push(k, k / 1000, [0.0])
        if frame is not None:
            indices.append(frame.frame_index)
            windows.append(frame.window_ticks)
    assert indices == list(range(indices[0], indices[0] + len(indices)))  # sem saltos
    assert windows[25] == 20  # janela em curso termina com 50 FPS
    assert set(windows[27:]) <= {16, 17}
    assert dec.fps == 60


def test_fps_is_clamped_and_same_value_is_noop() -> None:
    dec = FrameDecimator(1000, 10, _agg(Aggregation.LAST))
    assert dec.fps == 30
    dec.set_fps(30)
    dec.set_fps(99)
    assert FrameDecimator.clamp_fps(99) == 60
    with pytest.raises(ValueError, match="sim_hz"):
        FrameDecimator(50, 50, _agg(Aggregation.LAST))


def test_subscribe_fps_out_of_range_gives_error() -> None:
    catalog = build_catalog(4, True)
    result = apply_subscribe({"channels": ["rpm"], "fps": 25}, ClientSubscription(), catalog, 4)
    assert ("WS_FPS_OUT_OF_RANGE", "fps 25 fora de 30–60") in result.errors
    assert result.fps is None and result.subscription.channels == ("rpm",)
    ok = apply_subscribe({"channels": ["rpm"], "fps": 60}, ClientSubscription(), catalog, 4)
    assert ok.fps == 60 and not ok.errors
