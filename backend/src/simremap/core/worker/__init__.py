"""Worker do laço de simulação isolado do event loop (platform-foundation RF-11, RF-12).

Os módulos importados dentro do worker (``protocol``, ``queues``, ``logbridge``,
``loop``) nunca carregam ``fastapi`` nem o banco. ``SimWorkerHost`` e
``WorkerHandle`` (lado do event loop) são carregados sob demanda.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from simremap.core.worker.protocol import (
    DATA_OUTPUT_TYPES,
    SimTask,
    TaskSpec,
    WorkerConfig,
    WorkerState,
    WorkerStats,
)

if TYPE_CHECKING:
    from simremap.core.worker.host import AsyncOutputStream, SimWorkerHost, WorkerHandle

__all__ = [
    "DATA_OUTPUT_TYPES",
    "AsyncOutputStream",
    "SimTask",
    "SimWorkerHost",
    "TaskSpec",
    "WorkerConfig",
    "WorkerHandle",
    "WorkerState",
    "WorkerStats",
]

_LAZY = frozenset({"AsyncOutputStream", "SimWorkerHost", "WorkerHandle"})


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from simremap.core.worker import host

        return getattr(host, name)
    raise AttributeError(name)
