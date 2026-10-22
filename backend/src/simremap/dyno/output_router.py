"""Consumo das saídas do worker no event loop (T415; D-05; simulation-bus 3.6).

Uma tarefa por sessão lê ``WorkerHandle.outputs()`` (faixa crítica primeiro) e:

- ``run.state``/``telemetry.frame``/``event.*``/``error`` → ``SessionStream.publish``
  (``seq`` atribuído aqui) e estado da sessão;
- ``ack`` → resolve o pedido pendente (``request_id``) do serviço ou das portas;
- ``damage.trace`` → guarda o snapshot do dano da puxada para o laudo;
- ``run.result`` → grava o ``DynoRun`` (repositório, com ``persisted = false`` se o banco
  falhar), ``baseline_run_id``, ``engine_locked``; ``ForensicService.persist_failures``,
  ``persist_engine_health`` e ``submit`` do laudo (``failure`` em ``engine_failed``,
  ``near_miss`` com avisos de dano); resolve quem espera a puxada;
- ``worker.crashed``/``worker.setup_failed`` → puxada ativa ``aborted``
  (``internal_error``), envelope ``error`` ``SIM_WORKER_UNAVAILABLE`` fatal e sessão sem
  worker (comandos seguintes: 503).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import orjson

from simremap.core.logging import get_logger
from simremap.damage.contracts import EngineHealth, FailureEvent
from simremap.dyno.contracts import TERMINAL_RUN_STATES, AbortReason, DynoRun, RunState
from simremap.dyno.runs import forensic_report_url
from simremap.dyno.trace_codec import decode_trace

if TYPE_CHECKING:
    from simremap.dyno.session import DynoService, SessionRuntime

__all__ = ["OutputRouter"]

log = get_logger("simremap.dyno")


class OutputRouter:
    """Despacha os envelopes do worker de uma sessão."""

    def __init__(self, service: DynoService, rt: SessionRuntime) -> None:
        self.service = service
        self.rt = rt

    async def run(self) -> None:
        try:
            async for raw in self.rt.handle.outputs():
                try:
                    await self.dispatch(raw)
                except Exception as exc:  # um envelope inválido não para a sessão
                    log.error(
                        "dyno.output_failed",
                        session_id=self.rt.session_id,
                        detail=f"{type(exc).__name__}: {exc}"[:200],
                    )
        finally:
            if not self.rt.closing and not self.rt.worker_failed:
                await self._worker_lost("worker_exited")

    async def dispatch(self, raw: bytes) -> None:
        envelope = orjson.loads(raw)
        kind = envelope.get("type")
        payload: dict[str, Any] = envelope.get("payload") or {}
        rt = self.rt
        t = float(envelope.get("t_sim_s", 0.0))
        if t > rt.view.t_sim_s:
            rt.update(t_sim_s=t)
        if kind == "ack":
            future = rt.acks.get(str(payload.get("request_id")))
            if future is not None and not future.done():
                future.set_result(payload)
            return
        if kind == "session.ready":
            rt.rod_weights = [float(w) for w in payload.get("rod_weights", [])]
            rt.spectrum_available = bool(payload.get("spectrum_available", False))
            state = payload.get("ecu_state")
            if state in ("oem", "awaiting_base_setup", "standalone_ready"):
                rt.update(ecu_state=state)
            return
        if kind == "damage.trace":
            rt.traces[str(payload["run_id"])] = (str(payload["kind"]), payload["trace"])
            return
        if kind == "run.result":
            await self._run_result(payload)
            return
        if kind in ("worker.crashed", "worker.setup_failed"):
            await self._worker_lost(str(payload.get("reason", kind)))
            return
        if kind == "run.state":
            self._run_state(payload)
        elif (
            kind == "event.failure"
            and payload.get("catastrophic")
            and not payload.get("simulated_only")
        ):
            rt.update(engine_locked=True)
        rt.stream.publish(envelope)

    def _run_state(self, payload: dict[str, Any]) -> None:
        """Estado intermédio da puxada; os terminais só valem com o ``run.result``."""
        rt = self.rt
        rid = payload.get("run_id")
        run = rt.runs.get(str(rid)) if rid else None
        state = RunState(payload["state"])
        if run is None or state in TERMINAL_RUN_STATES:
            return
        rt.runs[run.run_id] = run.model_copy(update={"state": state})

    async def _run_result(self, payload: dict[str, Any]) -> None:
        rt = self.rt
        service = self.service
        run = DynoRun.model_validate(payload["run"])
        extra = rt.run_events.pop(run.run_id, set())
        if extra and run.summary is not None:
            codes = sorted(set(run.summary.event_codes) | extra)
            run = run.model_copy(
                update={"summary": run.summary.model_copy(update={"event_codes": codes})}
            )
        if not await service.repo.save_run(run) and service.repo.available:
            run = run.model_copy(update={"persisted": False})
        rod_weights = [float(w) for w in payload.get("rod_weights", [])] or rt.rod_weights
        rt.rod_weights = rod_weights
        # O laudo é agendado antes de a puxada terminal ficar visível (GET /runs e o
        # GET do laudo nunca veem "engine_failed" sem laudo pendente ou pronto).
        forensic = service.forensic
        trace = rt.traces.pop(run.run_id, None)
        if forensic is not None:
            failures = [FailureEvent.model_validate(f) for f in payload.get("failures", [])]
            await forensic.persist_failures(failures)
            health = payload.get("health")
            if health is not None:
                await forensic.persist_engine_health(
                    EngineHealth.model_validate(health), rod_weights, tick=run.ended_at_tick or 0
                )
            if trace is not None:
                kind, raw_trace = trace
                base = rt.runs.get(rt.view.baseline_run_id or "")
                if base is not None and base.run_id == run.run_id:
                    base = None
                forensic.submit(
                    decode_trace(raw_trace),
                    run,
                    base,
                    None,
                    "failure" if kind == "failure" else "near_miss",
                )
                rt.last_forensic_report_url = forensic_report_url(run.run_id)
        engine_locked = bool(payload.get("engine_locked"))
        baseline = rt.view.baseline_run_id
        if payload.get("is_baseline") and baseline is None:
            baseline = run.run_id
        rt.update(
            active_run_id=None,
            engine_locked=engine_locked,
            baseline_run_id=baseline,
            state="engine_locked" if engine_locked else "ready",
        )
        rt.runs[run.run_id] = run
        await service.repo.save_session(
            rt.view, data_version=rt.data_version, catalog_sha256=rt.catalog_sha256
        )
        future = rt.run_done.pop(run.run_id, None)
        if future is not None and not future.done():
            future.set_result(run)
        log.info(
            "dyno.run_finished",
            session_id=rt.session_id,
            run_id=run.run_id,
            state=run.state.value,
            abort_reason=None if run.abort_reason is None else run.abort_reason.value,
            t_sim_s=rt.view.t_sim_s,
            persisted=run.persisted,
        )

    async def _worker_lost(self, reason: str) -> None:
        rt = self.rt
        if rt.worker_failed:
            return
        rt.worker_failed = True
        rid = rt.view.active_run_id
        if rid is not None:
            run = rt.runs.get(rid)
            if run is not None and run.state not in TERMINAL_RUN_STATES:
                run = run.model_copy(
                    update={"state": RunState.ABORTED, "abort_reason": AbortReason.INTERNAL_ERROR}
                )
                rt.runs[rid] = run
                with contextlib.suppress(Exception):
                    await self.service.repo.save_run(run)
            future = rt.run_done.pop(rid, None)
            if future is not None and not future.done() and run is not None:
                future.set_result(run)
        rt.update(active_run_id=None)
        for pending in rt.acks.values():
            if not pending.done():
                pending.set_exception(TimeoutError("worker indisponível"))
        rt.stream.publish(
            {
                "type": "error",
                "t_sim_s": rt.view.t_sim_s,
                "payload": {
                    "code": "SIM_WORKER_UNAVAILABLE",
                    "title": "Worker de simulação indisponível",
                    "detail": reason,
                    "fatal": True,
                },
            }
        )
        log.error("dyno.worker_lost", session_id=rt.session_id, reason=reason)
