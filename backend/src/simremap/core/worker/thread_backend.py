"""Backend ``thread`` do ``SimWorkerHost`` (platform-foundation RF-11; D-04; T233).

O laço corre numa ``threading.Thread`` dedicada (nunca na thread do event loop),
com ``queue.Queue`` limitadas; a ponte para asyncio é a mesma do modo ``process``
(``loop.run_in_executor`` numa thread leitora dedicada, ver ``host.AsyncOutputStream``).
Usado nos testes (``SIMREMAP_WORKER_MODE=thread``) e como alternativa medida pelo
benchmark de D-04. Uma thread não pode ser terminada à força: em ``terminate`` a
thread é abandonada (``daemon``) e o host regista ``worker.stop_timeout``.
"""

from __future__ import annotations

import threading
from collections.abc import MutableSequence
from typing import Final

from simremap.core.worker.loop import WorkerSpec, run_worker
from simremap.core.worker.protocol import STATS_SIZE, TaskSpec, WorkerConfig
from simremap.core.worker.queues import WorkerChannels, make_thread_channels

__all__ = ["ThreadBackend"]

THREAD_NAME_PREFIX: Final = "simworker-"


class ThreadBackend:
    """Uma sessão do worker numa thread dedicada."""

    @property
    def mode(self) -> str:
        return "thread"

    def __init__(
        self,
        session_id: str,
        task_spec: TaskSpec,
        init_payload: bytes,
        sim_hz: int,
        config: WorkerConfig,
    ) -> None:
        self.channels: WorkerChannels = make_thread_channels(config)
        self.stats: MutableSequence[float] = [0.0] * STATS_SIZE
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=run_worker,
            args=(
                WorkerSpec(task_spec, init_payload, sim_hz),
                self.channels,
                self.stats,
                self._stop,
                config,
            ),
            name=f"{THREAD_NAME_PREFIX}{session_id}",
            daemon=True,
        )

    @property
    def ident(self) -> int | None:
        """Identificador da thread do worker (``None`` antes de ``start``)."""
        return self._thread.ident

    def start(self) -> None:
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def terminate(self) -> None:
        """Sem paragem forçada de threads: a thread ``daemon`` é abandonada."""
        self._stop.set()

    def close(self) -> None:
        """Nada a libertar: as filas ``queue.Queue`` são recolhidas pelo GC."""
