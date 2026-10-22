"""Montagem do log no event loop (T337, T340; tel RF-13, RF-15; EC-07, EC-15, EC-16)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from tel_helpers import records

from simremap.core.errors import SimRemapError
from simremap.dyno.sampler import TickRecord
from simremap.telemetry.broadcaster import TelemetryStream
from simremap.telemetry.logbook import Logbook, SessionMeta
from simremap.telemetry.sampler import LOG_BLOCK, LOG_OPEN, TelemetrySampler

META = SessionMeta("hatch-20t-gdi", "oem-stage", "e27", 7, "a" * 64)
RUN = "01JAB0000000000000000000BA"


def _feed(stream: TelemetryStream, sampler: TelemetrySampler, recs: list[TickRecord]) -> None:
    for rec in recs:
        sampler.on_tick(rec)
        for raw in sampler.drain():
            stream.publish(raw)


def _state(state: str, t: float, run_id: str = RUN) -> dict[str, Any]:
    return {"type": "run.state", "t_sim_s": t, "payload": {"run_id": run_id, "state": state}}


async def test_session_closed_without_log_end_finalizes_with_received_blocks(
    hatch_record: TickRecord,
) -> None:
    book = Logbook(None, lambda sid, rid: META, end_grace_s=0.0)
    stream = TelemetryStream("s", book)
    sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
    stream.publish(_state("arming", 0.0))  # chega antes do log_open (evento precoce)
    _feed(stream, sampler, records(hatch_record, 600, run_id=RUN))
    stream.publish(_state("aborted", 0.599))
    stream.close()  # sessão apagada: o worker não chega a mandar o último bloco
    await book.wait_idle()
    data = book.last_closed
    assert data is not None and data.header.terminal_state == "aborted"
    assert data.header.n_samples == 500  # 2 blocos de 250 ms recebidos
    assert [e.payload["state"] for e in data.header.events] == ["arming", "aborted"]


async def test_terminal_without_log_end_uses_timeout(hatch_record: TickRecord) -> None:
    book = Logbook(None, lambda sid, rid: META, end_grace_s=0.0, end_timeout_s=0.01)
    stream = TelemetryStream("s", book)
    sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
    _feed(stream, sampler, records(hatch_record, 260, run_id=RUN))
    stream.publish(_state("completed", 0.26))
    assert book.is_pending(RUN)
    await book.wait_idle()
    assert not book.is_pending(RUN) and book.last_closed is not None
    assert book.last_closed.header.n_samples == 250


async def test_worker_crash_discards_partial_log(hatch_record: TickRecord) -> None:
    book = Logbook(None, lambda sid, rid: META)
    stream = TelemetryStream("s", book)
    sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
    _feed(stream, sampler, records(hatch_record, 300, run_id=RUN))
    stream.publish(_state("completed", 0.3))  # agenda o timeout
    stream.publish(
        {
            "type": "error",
            "t_sim_s": 0.3,
            "payload": {"code": "SIM_WORKER_UNAVAILABLE", "title": "x", "fatal": True},
        }
    )
    await book.wait_idle()
    assert RUN in book.discarded and not book.is_pending(RUN)
    assert await book.finalize(RUN) is None


async def test_invalid_blocks_and_missing_meta(
    hatch_record: TickRecord, caplog: pytest.LogCaptureFixture
) -> None:
    book = Logbook(None, lambda sid, rid: None, end_grace_s=0.0)
    stream = TelemetryStream("s", book)
    sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
    _feed(stream, sampler, records(hatch_record, 10, run_id=RUN))
    stream.publish(
        {"type": LOG_BLOCK, "payload": {"run_id": RUN, "n": 3, "t_sim_s": "", "data": ""}}
    )
    stream.publish(
        {
            "type": LOG_OPEN,
            "payload": {
                "run_id": "x",
                "n_cyl": 4,
                "has_turbo": True,
                "channels": ["rpm"],
                "start_tick": 0,
                "sim_hz": 1000,
            },
        }
    )
    assert not book.is_pending("x")  # canais diferentes do catálogo: ignorado
    sampler.on_tick(replace(hatch_record, tick=10, t_sim_s=0.01, run_id=None))
    for raw in sampler.drain():
        stream.publish(raw)
    await book.wait_idle()
    assert RUN in book.discarded  # sem metadados da sessão: log não construído
    assert any("datalog.block_invalid" in r.getMessage() for r in caplog.records)


async def test_save_errors_are_kept_or_logged(hatch_record: TickRecord) -> None:
    class Repo:
        def __init__(self, code: str) -> None:
            self.code = code
            self.saved: list[Any] = []

        async def save(self, data: Any, *, log_id: str, source: str) -> None:
            if self.code:
                raise SimRemapError("falha", code=self.code)
            self.saved.append(data)

    for code, kept in (("STORAGE_FULL", True), ("LOG_ALREADY_IMPORTED", False)):
        repo = Repo(code)
        book = Logbook(repo, lambda sid, rid: META, end_grace_s=0.0, clock=lambda: 0.0)  # type: ignore[arg-type]
        stream = TelemetryStream("s", book)
        sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
        _feed(stream, sampler, records(hatch_record, 30, run_id=RUN))
        sampler.on_tick(replace(hatch_record, tick=30, t_sim_s=0.03, run_id=None))
        for raw in sampler.drain():
            stream.publish(raw)
        await book.wait_idle()
        assert (book.in_memory(RUN) is not None) is kept
        if kept:
            repo.code = ""
            assert await book.retry_memory(RUN) is not None and repo.saved
            assert book.in_memory(RUN) is None


async def test_shutdown_flushes_pending(hatch_record: TickRecord) -> None:
    book = Logbook(None, lambda sid, rid: META)
    stream = TelemetryStream("s", book)
    sampler = TelemetrySampler("s", 1000, 50, 4, 13.2)
    _feed(stream, sampler, records(hatch_record, 300, run_id=RUN))
    assert book.is_pending(RUN)
    await book.shutdown()
    assert not book.is_pending(RUN) and book.last_closed is not None
    assert book.last_closed.header.terminal_state == "aborted"  # sem run.state terminal
