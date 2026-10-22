"""Processo real ``python -m simremap.api.serve`` (RF-02, RF-13, EC-01, EC-08, EC-12)."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from simremap.api.serve import EXIT_STARTUP_FAILURE, GracefulServer, build_config, main

SRC = Path(__file__).resolve().parents[2] / "src"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SIMREMAP_")}
    env.pop("DATABASE_URL", None)
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "SIMREMAP_DATA_DIR": str(tmp_path / "data"),
            "SIMREMAP_STATIC_DIR": str(tmp_path / "static"),
            "SIMREMAP_LOG_LEVEL": "INFO",
            **extra,
        }
    )
    return env


def _spawn(tmp_path: Path, port: int, **extra: str) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603 - interpretador atual com módulo fixo
        [sys.executable, "-m", "simremap.api.serve", "--host", "127.0.0.1", "--port", str(port)],
        env=_env(tmp_path, **extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _json_lines(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_sigterm_graceful_exit_0_and_json_only(tmp_path: Path) -> None:
    port = _free_port()
    proc = _spawn(tmp_path, port)
    url = f"http://127.0.0.1:{port}/api/v1/health"
    deadline = time.monotonic() + 30
    body: dict[str, object] = {}
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                body = json.load(resp)
            break
        except OSError:
            time.sleep(0.2)
    assert body.get("status") == "ok"
    t0 = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    output, _ = proc.communicate(timeout=15)
    assert time.monotonic() - t0 < 10  # EC-12
    assert proc.returncode == 0
    events = _json_lines(output)  # 100 % das linhas são JSON (RF-13)
    names = [e["event"] for e in events]
    assert "startup.complete" in names and "shutdown.database" in names
    assert all({"ts", "level", "logger", "event", "request_id"} <= set(e) for e in events)


def test_database_unavailable_exit_3(tmp_path: Path) -> None:
    proc = _spawn(
        tmp_path,
        _free_port(),
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:1/nada",
        SIMREMAP_DB_CONNECT_RETRIES="1",
    )
    output, _ = proc.communicate(timeout=30)
    assert proc.returncode == EXIT_STARTUP_FAILURE == 3
    failed = [e for e in _json_lines(output) if e["event"] == "startup.failed"]
    assert failed and failed[0]["code"] == "DATABASE_UNAVAILABLE"


def test_invalid_catalog_exit_4(tmp_path: Path) -> None:
    empty = tmp_path / "catalogo-vazio"
    empty.mkdir()
    proc = _spawn(tmp_path, _free_port(), SIMREMAP_CATALOG_DIR=str(empty))
    output, _ = proc.communicate(timeout=30)
    assert proc.returncode == 4
    failed = [e for e in _json_lines(output) if e["event"] == "startup.failed"]
    assert failed and failed[0]["code"] == "CATALOG_INVALID"


def test_invalid_settings_exit_2(tmp_path: Path) -> None:
    proc = _spawn(tmp_path, _free_port(), SIMREMAP_SIM_HZ="2000")
    output, _ = proc.communicate(timeout=30)
    assert proc.returncode == 2
    assert any(e["event"] == "startup.invalid_settings" for e in _json_lines(output))


def test_build_config_defaults() -> None:
    config = build_config()
    assert (config.host, config.port) == ("127.0.0.1", 8000)
    assert config.access_log is False
    assert config.log_config is None
    assert config.ws_ping_interval == 15.0  # D-WS-05


def test_capture_signals_restores_handlers_without_reraise() -> None:
    server = GracefulServer(build_config("127.0.0.1", _free_port()))
    before = signal.getsignal(signal.SIGTERM)
    with server.capture_signals():
        assert signal.getsignal(signal.SIGTERM) == server.handle_exit
        server.handle_exit(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) == before
    assert server.should_exit


def test_main_returns_3_when_not_started(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GracefulServer, "run", lambda self, sockets=None: None)
    assert main(["--port", "1"]) == 3
