"""Datalog à taxa total (T168, T333, T337; tel RF-14 a RF-16; EC-14, EC-17; D-12;
file-formats 4.4)."""

from __future__ import annotations

import gzip
import json
import math
import struct
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tel_helpers import make_sampler_task, pump, records, start_run

import simremap.telemetry.sampler as sampler_module
from simremap.dyno.sampler import TickRecord
from simremap.telemetry.broadcaster import TelemetryStream
from simremap.telemetry.datalog import (
    MAGIC,
    LogData,
    canonical_header,
    compute_sha256,
    decode_simlog,
    encode_simlog,
    read_simlog,
    write_simlog,
)
from simremap.telemetry.errors import TelemetryError
from simremap.telemetry.logbook import Logbook, SessionMeta
from simremap.telemetry.sampler import TelemetrySampler

META = SessionMeta("hatch-20t-gdi", "oem-stage", "e27", 7, "a" * 64)
RUN = "01JAB0000000000000000000DA"


def _event(type_: str, t: float, **payload: Any) -> dict[str, Any]:
    return {"type": type_, "t_sim_s": t, "payload": {"run_id": RUN, **payload}}


async def _synthetic_log(
    base: TickRecord, n: int, *, extra_events: list[dict[str, Any]] | None = None
) -> tuple[LogData, TelemetrySampler]:
    sampler = TelemetrySampler("sess-1", 1000, 50, 4, 13.2)
    book = Logbook(None, lambda sid, rid: META, end_grace_s=0.0)
    stream = TelemetryStream("sess-1", book)
    start = 5000
    stream.publish(_event("run.state", start / 1000, state="arming", phase="arming"))
    for rec in records(base, n, start_tick=start, run_id=RUN):
        sampler.on_tick(rec)
        for raw in sampler.drain():
            stream.publish(raw)
    for event in extra_events or []:
        stream.publish(event)
    stream.publish(_event("run.state", (start + n - 1) / 1000, state="completed", phase="done"))
    sampler.on_tick(replace(base, tick=start + n, t_sim_s=(start + n) / 1000, run_id=None))
    for raw in sampler.drain():
        stream.publish(raw)
    await book.wait_idle()
    assert book.last_closed is not None
    return book.last_closed, sampler


async def test_15s_at_1000hz_gives_15000_samples(hatch_record: TickRecord) -> None:
    data, sampler = await _synthetic_log(hatch_record, 15_000)
    header = data.header
    assert header.n_samples == 15_000 and data.columns.shape == (len(sampler.catalog), 15_000)  # type: ignore[arg-type]
    assert header.start_tick == 5000 and header.sim_hz == 1000
    assert header.terminal_state == "completed" and not header.truncated
    assert [c.name for c in header.channels] == list(sampler.catalog.names)  # type: ignore[union-attr]
    assert data.t_sim_s[0] == 5.0 and data.t_sim_s[-1] == pytest.approx(19.999)
    assert data.column("rpm")[0] == np.float32(hatch_record.state.rpm)
    assert [e.index for e in header.events] == [0, 14_999]
    assert header.pulls[0].start_index == 0 and header.pulls[0].end_index == 15_000


async def test_simlog_format_and_canonical_hash(hatch_record: TickRecord, tmp_path: Path) -> None:
    data, _ = await _synthetic_log(hatch_record, 1200)
    path = tmp_path / "logs" / f"{RUN}.simlog.gz"
    size = write_simlog(path, data)
    raw = gzip.decompress(path.read_bytes())
    assert size == path.stat().st_size
    assert raw.startswith(MAGIC)
    (hlen,) = struct.unpack_from("<I", raw, 8)
    header_bytes = raw[12 : 12 + hlen]
    assert header_bytes == canonical_header(data.header)
    parsed = json.loads(header_bytes)
    assert list(parsed) == sorted(parsed)  # chaves ordenadas
    assert b": " not in header_bytes and b", " not in header_bytes
    assert raw[-64:].decode() == data.sha256
    n, n_ch = data.header.n_samples, len(data.header.channels)
    assert len(raw) == 12 + hlen + 8 * n + 4 * n * n_ch + 64
    again = read_simlog(path)
    assert again.sha256 == data.sha256 and np.array_equal(again.t_sim_s, data.t_sim_s)
    # Mudar 1 bit de 1 amostra muda o hash; metadados voláteis não.
    flipped = data.columns.copy()
    flipped.view(np.uint32)[0, 10] ^= 1
    assert compute_sha256(data.header, data.t_sim_s, flipped) != data.sha256
    data.log_id = "outro"
    data.source = "imported"
    assert data.recomputed_sha256() == data.sha256
    # Arquivo adulterado ⇒ LOG_CORRUPTED.
    bad = bytearray(encode_simlog(data))
    bad[-70] ^= 0xFF
    with pytest.raises(TelemetryError) as info:
        decode_simlog(bytes(bad))
    assert info.value.error_code == "LOG_CORRUPTED"
    with pytest.raises(TelemetryError):
        decode_simlog(b"NOTALOG" + bytes(20))
    (tmp_path / "x.simlog.gz").write_bytes(b"lixo")
    with pytest.raises(TelemetryError):
        read_simlog(tmp_path / "x.simlog.gz")


async def test_truncated_above_300s_keeps_events(
    hatch_record: TickRecord, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sampler_module, "LOG_MAX_S", 1.0)  # 300 s → 1 s para o teste
    late = _event("event.knock", 6.4, cylinder=2, intensity=0.5)
    data, _ = await _synthetic_log(hatch_record, 1500, extra_events=[late])
    assert data.header.truncated is True
    assert data.header.n_samples == 1000
    knock = [e for e in data.header.events if e.type == "event.knock"]
    assert knock and knock[0].index == 999  # evento depois do limite fica no fim


async def test_non_finite_is_nan_in_log(hatch_record: TickRecord) -> None:
    for bad in (math.inf, math.nan):
        state = hatch_record.state.model_copy(update={"torque_nm": bad})
        data, _ = await _synthetic_log(replace(hatch_record, state=state), 300)
        bits = data.column("torque_nm").view(np.uint32)
        assert (bits == 0x7FC00000).all()  # NaN quiet canónico


def test_frames_carry_nan_as_null(hatch_record: TickRecord) -> None:
    sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
    rec = replace(hatch_record, state=hatch_record.state.model_copy(update={"torque_nm": math.inf}))
    for r in records(rec, 20):
        sampler.on_tick(r)
    import orjson

    frames = [orjson.loads(raw) for raw in sampler.drain()]
    assert frames and frames[0]["payload"]["channels"]["torque_nm"] is None


async def test_multi_pull_segments_from_run_state(hatch_record: TickRecord) -> None:
    events = [
        _event("run.state", 5.0 + 1.0, state="running", phase="pull", pull_index=1),
        _event("run.state", 5.0 + 2.0, state="running", phase="arming", pull_index=2),
        _event("run.state", 5.0 + 2.5, state="running", phase="pull", pull_index=2),
        _event("run.state", 5.0 + 4.0, state="running", phase="arming", pull_index=3),
    ]
    data, _ = await _synthetic_log(hatch_record, 6000, extra_events=events)
    pulls = data.header.pulls
    assert [p.pull_index for p in pulls] == [1, 2, 3]
    assert all(p.start_index < p.end_index for p in pulls)
    assert [p.start_index for p in pulls] == [0, 2000, 4000]
    assert pulls[-1].end_index == 6000 and pulls[-1].state == "completed"


def test_mark_pull_segments_from_worker(hatch_record: TickRecord) -> None:
    sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
    recs = records(hatch_record, 300, run_id=RUN)
    for i, rec in enumerate(recs):
        if i in (0, 100, 200):
            if i == 0:
                sampler.on_tick(rec)
                sampler.mark_pull(1)
                continue
            sampler.mark_pull(i // 100 + 1)
        sampler.on_tick(rec)
    sampler.close_log()
    import orjson

    end = next(orjson.loads(r) for r in sampler.drain() if b"telemetry.log_end" in r)
    pulls = end["payload"]["pulls"]
    assert [(p["pull_index"], p["start_index"], p["end_index"]) for p in pulls] == [
        (1, 1, 100),
        (2, 100, 200),
        (3, 200, 300),
    ]
    sampler.mark_pull(4)  # sem log aberto: ignorado


async def test_real_loop_log_determinism_and_size() -> None:
    """Mesma seed, comandos e ids ⇒ mesmo sha256 (10/10); ≤ 3 MB por 15 s a 1000 Hz."""
    hashes = set()
    sizes = []
    for _ in range(10):
        task = make_sampler_task()
        book = Logbook(None, lambda sid, rid: META, end_grace_s=0.0)
        stream = TelemetryStream(task.session.payload.session_id, book)
        start_run(task, {"run_type": "sweep_pull", "end_rpm": 3000, "ramp_rate_rpm_s": 1000}, RUN)
        pump(task, stream, 2500)
        task.handle_command({"type": "run.abort", "run_id": RUN, "reason": "user_abort"})
        pump(task, stream, 50, until=lambda e: e["type"] == "telemetry.log_end")
        await book.wait_idle()
        data = book.last_closed
        assert data is not None and data.header.terminal_state == "aborted"
        hashes.add(data.sha256)
        sizes.append(
            len(gzip.compress(encode_simlog(data), compresslevel=6)) / data.header.n_samples
        )
    assert len(hashes) == 1
    assert max(sizes) * 15_000 <= 3 * 1024 * 1024
