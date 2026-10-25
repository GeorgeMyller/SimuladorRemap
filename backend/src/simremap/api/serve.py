"""Ponto de entrada de produção: ``python -m simremap.api.serve`` (CMD do Dockerfile).

Equivale a ``uvicorn simremap.api.main:app --no-access-log --ws-ping-interval 15`` com
três diferenças exigidas pela spec (RF-02, RF-13, EC-01, EC-08, EC-12):

- o logging do uvicorn não é configurado à parte: todas as linhas de stdout saem do
  logging JSON da app (configurado ao importar ``simremap.api.main:app``);
- ``SIGTERM``/``SIGINT`` fazem o shutdown gracioso (worker stop + join 5 s, engine
  dispose) e o processo termina com código **0** (o uvicorn reemite o sinal: 143);
- códigos de saída: 0 (paragem normal), 2 (``Settings`` inválido), 3 (arranque falhou,
  ex.: ``DATABASE_UNAVAILABLE`` após 5 tentativas), 4 (``CATALOG_INVALID``) — o código da
  ``StartupError`` do lifespan quando existe, 3 nas restantes falhas de arranque.

Ping do WebSocket a cada 15 s (D-WS-05; ``compose.dev.yaml`` usa o mesmo valor).
"""

from __future__ import annotations

import argparse
import signal
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Final

import uvicorn

__all__ = ["EXIT_STARTUP_FAILURE", "WS_PING_INTERVAL_S", "GracefulServer", "build_config", "main"]

EXIT_STARTUP_FAILURE: Final = 3
WS_PING_INTERVAL_S: Final = 15.0  # D-WS-05
_SIGNALS: Final = (signal.SIGINT, signal.SIGTERM)


class GracefulServer(uvicorn.Server):
    """``uvicorn.Server`` que não reemite o sinal capturado depois do shutdown."""

    @contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        original = {sig: signal.signal(sig, self.handle_exit) for sig in _SIGNALS}
        try:
            yield
        finally:
            for sig, handler in original.items():
                signal.signal(sig, handler)


def build_config(host: str = "127.0.0.1", port: int = 8000) -> uvicorn.Config:
    return uvicorn.Config(
        "simremap.api.main:app",
        host=host,
        port=port,
        access_log=False,
        log_config=None,
        ws_ping_interval=WS_PING_INTERVAL_S,
        timeout_graceful_shutdown=8,
        server_header=False,
        proxy_headers=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simremap.api.serve")
    # Padrão só loopback (D-32); o Dockerfile passa --host 0.0.0.0 dentro do container.
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    server = GracefulServer(build_config(args.host, args.port))
    try:
        server.run()
    except SystemExit as exc:  # o uvicorn termina com sys.exit(3) se o lifespan falha
        if exc.code != EXIT_STARTUP_FAILURE:
            raise
        return _startup_exit_code()
    return 0 if server.started else _startup_exit_code()


def _startup_exit_code() -> int:
    """Código da ``StartupError`` do lifespan (ex.: 4 em ``CATALOG_INVALID``) ou 3."""
    from simremap.api.main import last_startup_exit_code

    return last_startup_exit_code() or EXIT_STARTUP_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
