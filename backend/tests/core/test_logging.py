"""Logging JSON (T081, T228; RF-13, RF-20): 1 linha JSON por evento, sem IP nem nickname."""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from simremap.api.main import create_app
from simremap.core.logging import (
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    scrub_pii,
)
from simremap.core.request_context import request_id_var

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
REQUIRED = {"ts", "level", "logger", "event", "request_id"}


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    configure_logging("DEBUG", buffer)
    yield buffer
    configure_logging("INFO")
    clear_context()


def _lines(buffer: io.StringIO) -> list[dict[str, Any]]:
    raw = [line for line in buffer.getvalue().splitlines() if line.strip()]
    return [json.loads(line) for line in raw]


def test_one_json_line_per_event_with_required_fields(stream: io.StringIO) -> None:
    log = get_logger("simremap.test")
    log.info("test.first", value=1)
    log.warning("test.second", detail="várias\nlinhas")
    logging.getLogger("simremap.std").error("test.stdlib", extra={"code": "SIM_WORKER_BUSY"})
    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    events = _lines(stream)
    for event in events:
        assert REQUIRED <= set(event)
        assert TS.fullmatch(event["ts"])
        assert event["request_id"] is None
    assert [e["event"] for e in events] == ["test.first", "test.second", "test.stdlib"]
    assert [e["level"] for e in events] == ["info", "warning", "error"]
    assert events[0]["logger"] == "simremap.test"
    assert events[2]["logger"] == "simremap.std"
    assert events[2]["code"] == "SIM_WORKER_BUSY"


def test_request_id_and_bound_context(stream: io.StringIO) -> None:
    token = request_id_var.set("rid-42")
    try:
        bind_context(session_id="s-1", run_id="r-1")
        get_logger("simremap.test").info("test.ctx")
        clear_context("run_id")
        get_logger("simremap.test").info("test.ctx2")
    finally:
        request_id_var.reset(token)
    first, second = _lines(stream)
    assert first["request_id"] == "rid-42"
    assert (first["session_id"], first["run_id"]) == ("s-1", "r-1")
    assert second["session_id"] == "s-1"
    assert "run_id" not in second


def test_pii_keys_removed_and_values_masked(stream: io.StringIO) -> None:
    get_logger("simremap.test").info(
        "test.pii",
        nickname="lucas",
        email="lucas@example.com",
        client_ip="203.0.113.9",
        headers={"user-agent": "x"},
        detail="cliente 203.0.113.9 com lucas@example.com e fe80:0:0:0:1:2:3:4",
        nested={"ip": "10.0.0.1", "ok": ["198.51.100.1"]},
        profile_id="p-1",
    )
    logging.getLogger("simremap.std").info("std.pii", extra={"nickname": "rodrigo"})
    raw = stream.getvalue()
    for secret in ("lucas", "rodrigo", "203.0.113.9", "10.0.0.1", "198.51.100.1", "example.com"):
        assert secret not in raw
    event, std_event = _lines(stream)
    assert "nickname" not in event and "email" not in event and "headers" not in event
    assert event["detail"] == "cliente [ip] com [email] e [ip]"
    assert event["nested"] == {"ok": ["[ip]"]}
    assert event["profile_id"] == "p-1"
    assert "nickname" not in std_event


def test_scrub_pii_processor_directly() -> None:
    out = scrub_pii(None, "info", {"event": "x", "ip_addr": "1.2.3.4", "real_name": "Ana"})
    assert out == {"event": "x"}


def test_exception_has_exc_type_and_stack(stream: io.StringIO) -> None:
    try:
        raise ValueError("falha /tmp/segredo")
    except ValueError:
        get_logger("simremap.test").exception("test.exc")
    try:
        raise KeyError("k")
    except KeyError as exc:
        get_logger("simremap.test").error("test.exc2", exc_info=exc)
    first, second = _lines(stream)
    assert first["level"] == "error"
    assert first["exc_type"] == "ValueError"
    assert "Traceback" in first["stack"]
    assert second["exc_type"] == "KeyError"


def test_uvicorn_loggers_rerouted_and_access_disabled(stream: io.StringIO) -> None:
    logging.getLogger("uvicorn.access").info('203.0.113.9:5000 - "GET / HTTP/1.1" 200')
    logging.getLogger("uvicorn.error").info("Started server process")
    events = _lines(stream)
    assert [e["event"] for e in events] == ["Started server process"]
    assert events[0]["logger"] == "uvicorn.error"


def test_configure_is_idempotent() -> None:
    a, b = io.StringIO(), io.StringIO()
    configure_logging("INFO", a)
    configure_logging("INFO", b)
    try:
        get_logger("simremap.test").info("test.once")
        assert a.getvalue() == ""
        assert len(b.getvalue().splitlines()) == 1
        marked = [
            h for h in logging.getLogger().handlers if getattr(h, "_simremap_json_handler", False)
        ]
        assert len(marked) == 1
    finally:
        configure_logging("INFO")


async def test_smoke_http_logs_are_json_without_ip(
    settings_factory: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    app = create_app(settings_factory(log_level="INFO"))
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app, client=("203.0.113.77", 51234))
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            await ac.get("/api/v1/health?nickname=lucas", headers={"X-Request-ID": "smoke-1"})
            await ac.get("/api/v1/nao-existe")
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]  # todas as linhas são JSON válido
    assert all(REQUIRED <= set(e) for e in events)
    assert "203.0.113.77" not in out
    assert "lucas" not in out
    requests = [e for e in events if e["event"] == "http.request"]
    assert len(requests) == 2
    first = requests[0]
    assert first["request_id"] == "smoke-1"
    assert first["method"] == "GET"
    assert first["path"] == "/api/v1/health"
    assert first["status"] == 200
    assert first["duration_ms"] >= 0
    assert requests[1]["status"] == 404
    startup = [e["event"] for e in events if e["event"].startswith("startup.")]
    assert startup[:2] == ["startup.settings", "startup.database"]
