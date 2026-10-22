"""``SyntheticTask``: ``SimTask`` determinística para testes e benchmarks do worker.

Não depende da física. Usada pelos testes do ``SimWorkerHost`` (modos ``process`` e
``thread``) e pelo benchmark de D-04 enquanto o ``PhysicsOnlyTask`` (T408) não existe.

``init_payload`` (JSON, todos opcionais)::

    {"sim_hz": 1000, "fps": 50, "work_n": 0, "busy_us": 0, "knock_every": 0,
     "report_thread": false}

- ``fps``: frames ``telemetry.frame`` por segundo simulado (fronteira
  ``floor(k · fps / sim_hz)``, como o ``TelemetrySampler``).
- ``work_n``: tamanho de um produto matricial NumPy por tick (carga sintética).
- ``busy_us``: microssegundos de laço Python por tick, segurando o GIL como a física
  em Python puro (carga do benchmark de D-04). Não altera o estado determinístico.
- ``knock_every``: emite ``event.knock`` a cada N ticks (0 = nunca).
- ``report_thread``: no 1.º tick emite ``task.info`` com ``tick_thread``, ``pid``,
  ``fastapi_loaded`` e as variáveis BLAS (verificação de isolamento).

Comandos (``type``): ``echo`` (→ ``ack``), ``run.state`` (→ ``run.state``), ``crash``
(exceção no próximo tick), ``hang`` (``seconds``: bloqueia o tick), ``flood_critical``
(``count`` envelopes ``ack`` de uma vez), ``log_burst`` (``count`` linhas pela
``logbridge``), ``fail_teardown``.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

import orjson

from simremap.core.worker.logbridge import worker_log

__all__ = ["SyntheticTask"]


class SyntheticTask:
    """Tarefa determinística: o estado depende só da contagem de ticks e dos comandos."""

    def __init__(self) -> None:
        self.sim_hz = 1000
        self.fps = 50
        self.work_n = 0
        self.busy_s = 0.0
        self.knock_every = 0
        self.report_thread = False
        self.tick_index = 0
        self.frame_index = -1
        self.value = 0.0
        self._outputs: list[bytes] = []
        self._crash_next = False
        self._hang_s = 0.0
        self._fail_teardown = False
        self._matrix: Any = None

    # ------------------------------------------------------------------ helpers
    @property
    def t_sim_s(self) -> float:
        return self.tick_index / self.sim_hz

    def _emit(self, kind: str, **payload: Any) -> None:
        self._outputs.append(
            orjson.dumps({"v": 1, "type": kind, "t_sim_s": self.t_sim_s, "payload": payload})
        )

    # ------------------------------------------------------------------ SimTask
    def setup(self, init_payload: bytes) -> None:
        options = orjson.loads(init_payload) if init_payload else {}
        if not isinstance(options, dict):
            raise ValueError("init_payload deve ser um objeto JSON")
        if options.get("fail_setup"):
            raise RuntimeError("falha de setup pedida pelo teste")
        self.sim_hz = int(options.get("sim_hz", 1000))
        self.fps = int(options.get("fps", 50))
        self.work_n = int(options.get("work_n", 0))
        self.busy_s = float(options.get("busy_us", 0)) / 1e6
        self.knock_every = int(options.get("knock_every", 0))
        self.report_thread = bool(options.get("report_thread", False))
        if self.work_n > 0:
            import numpy as np  # noqa: PLC0415 - só com carga sintética

            base = np.arange(self.work_n * self.work_n, dtype=np.float64)
            self._matrix = (base.reshape(self.work_n, self.work_n) % 7.0) / 7.0
        self._emit("run.state", state="idle")

    def handle_command(self, command: dict[str, object]) -> None:
        kind = command.get("type")
        if kind == "echo":
            self._emit("ack", command="echo", value=command.get("value"))
        elif kind == "run.state":
            self._emit("run.state", state=command.get("state", "idle"))
        elif kind == "crash":
            self._crash_next = True
        elif kind == "hang":
            self._hang_s = float(str(command.get("seconds", 3.0)))
        elif kind == "flood_critical":
            for i in range(int(str(command.get("count", 1)))):
                self._emit("ack", command="flood", index=i)
        elif kind == "log_burst":
            log = worker_log()
            for i in range(int(str(command.get("count", 1)))):
                log.info("synthetic.log", index=i)
        elif kind == "fail_teardown":
            self._fail_teardown = True
        else:
            self._emit("ack", command=str(kind), ignored=True)

    def tick(self) -> None:
        if self._crash_next:
            raise RuntimeError("falha sintética no tick")
        if self._hang_s > 0:
            hang, self._hang_s = self._hang_s, 0.0
            time.sleep(hang)
        if self.report_thread and self.tick_index == 0:
            self._emit(
                "task.info",
                tick_thread=threading.get_ident(),
                pid=os.getpid(),
                fastapi_loaded="fastapi" in sys.modules,
                sqlalchemy_loaded="sqlalchemy" in sys.modules,
                omp_threads=os.environ.get("OMP_NUM_THREADS"),
                openblas_threads=os.environ.get("OPENBLAS_NUM_THREADS"),
            )
        if self.busy_s > 0:
            deadline = time.perf_counter() + self.busy_s
            spins = 0
            while time.perf_counter() < deadline:
                spins += 1
        self.tick_index += 1
        self.value = self.value * 0.999 + 1.0
        if self._matrix is not None:
            self.value += float((self._matrix @ self._matrix).trace()) * 1e-9
        if self.knock_every and self.tick_index % self.knock_every == 0:
            self._emit("event.knock", cylinder=1 + self.tick_index % 4, intensity=0.5)
        frame = (self.tick_index * self.fps) // self.sim_hz
        if frame != self.frame_index:
            self.frame_index = frame
            self._emit("telemetry.frame", frame_index=frame, rpm=round(800.0 + self.value, 6))

    def drain_outputs(self) -> list[bytes]:
        outputs, self._outputs = self._outputs, []
        return outputs

    def teardown(self) -> None:
        if self._fail_teardown:
            raise RuntimeError("falha sintética no teardown")
        self._emit("run.state", state="closed", ticks=self.tick_index)
