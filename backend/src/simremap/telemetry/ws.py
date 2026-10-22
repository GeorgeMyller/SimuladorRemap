"""Conexão do WebSocket ``/ws/v1/sessions/{session_id}/telemetry`` (tel RF-01, RF-02, RF-07,
RF-10, RF-22, RF-24; dyno RF-24; websocket-telemetry 1, 4, 7 e 8).

Handshake: ``Origin`` diferente da origem do servidor (e fora de ``cors_origins``) ⇒ 4403;
sessão inexistente ⇒ 4404; 5.ª conexão ⇒ 4429. Aceite a conexão, o servidor envia o
snapshot de ``run.state`` (``seq`` novo), os erros do resume e o replay (``seq``
original) e passa ao fluxo ao vivo com os canais padrão.

Duas tarefas por conexão: o envio (fila ``ConnectionQueue`` na ordem do ``seq``, filtro
por subscrição, limite de ``event.knock``) e a leitura (``control.*``, limites de 16 kB,
20 inválidas em 10 s e 100 mensagens/s ⇒ ``WS_RATE_LIMITED`` + 1008; 30 s sem mensagem ⇒
4408). Todo envelope local (``error``) recebe ``seq`` + 1 da sessão e sai pela mesma fila.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any, Final
from urllib.parse import urlparse

import orjson
from fastapi import WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect, WebSocketState

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.dyno.stream import SessionStream
from simremap.telemetry.broadcaster import (
    ClientRateLimiter,
    ClientSubscription,
    ConnectionQueue,
    FpsMeter,
    KnockRateGuard,
    TelemetryStream,
    apply_subscribe,
    render_frame,
)
from simremap.telemetry.contracts import MAX_CLIENT_MESSAGE_BYTES, WsClientMessage, WsErrorPayload
from simremap.telemetry.errors import CLOSE_CODES, ws_title
from simremap.telemetry.service import TelemetryService

__all__ = ["IDLE_TIMEOUT_S", "TelemetryConnection", "origin_allowed", "serve_telemetry"]

log = get_logger("simremap.telemetry")

IDLE_TIMEOUT_S: Final = 30.0
THROTTLE_MAX_PCT: Final = 100.0


def origin_allowed(websocket: WebSocket, allowed_origins: list[str]) -> bool:
    """``Origin`` ausente, igual à origem do servidor ou em ``cors_origins``."""
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    if origin.rstrip("/") in {o.rstrip("/") for o in allowed_origins}:
        return True
    host = websocket.headers.get("host", "")
    return urlparse(origin).netloc.lower() == host.lower()


def _now() -> float:
    return asyncio.get_running_loop().time()


async def _reject(websocket: WebSocket, reason: str) -> None:
    await websocket.accept()
    await websocket.close(code=CLOSE_CODES[reason], reason=reason)


async def serve_telemetry(
    websocket: WebSocket,
    service: TelemetryService | None,
    session_id: str,
    *,
    allowed_origins: list[str],
    idle_timeout_s: float = IDLE_TIMEOUT_S,
) -> None:
    """Handshake, limites e ciclo de vida de uma conexão."""
    if not origin_allowed(websocket, allowed_origins):
        await _reject(websocket, "WS_ORIGIN_FORBIDDEN")
        return
    stream = None if service is None else service.stream(session_id)
    if service is None or stream is None:
        await _reject(websocket, "SESSION_NOT_FOUND")
        return
    if not service.try_connect(session_id):
        await _reject(websocket, "WS_TOO_MANY_CONNECTIONS")
        return
    try:
        connection = TelemetryConnection(
            websocket, service, session_id, stream, idle_timeout_s=idle_timeout_s
        )
        await connection.run(_resume_from(websocket))
    finally:
        service.disconnect(session_id)


def _resume_from(websocket: WebSocket) -> int | None:
    raw = websocket.query_params.get("resume_from_seq")
    if raw is None or not raw.isdigit():
        return None
    return int(raw)


class TelemetryConnection:
    """Uma conexão aceite: preâmbulo, envio e leitura."""

    def __init__(
        self,
        websocket: WebSocket,
        service: TelemetryService,
        session_id: str,
        stream: SessionStream,
        *,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
        clock: Callable[[], float] = _now,
    ) -> None:
        self.ws = websocket
        self.service = service
        self.session_id = session_id
        self.stream = stream
        self.idle_timeout_s = idle_timeout_s
        self.clock = clock
        self.queue = ConnectionQueue()
        self.subscription = ClientSubscription()
        self.catalog = service.catalog(session_id)
        rt = service.runtime(session_id)
        self.n_cyl = rt.vehicle.engine.n_cyl if rt is not None else 8
        self.knock_guard = KnockRateGuard()
        self.fps_meter = FpsMeter()
        self.limiter = ClientRateLimiter(clock)
        self.close_code: int | None = None
        self._closed = asyncio.Event()
        self.sent = 0

    # ------------------------------------------------------------------ seq e envelopes
    def _allocate_seq(self) -> int:
        stream = self.stream
        if isinstance(stream, TelemetryStream):
            return stream.allocate_seq()
        stream.seq += 1
        return stream.seq

    def _t_now(self) -> float:
        stream = self.stream
        t = stream.replay_buffer.latest_t if isinstance(stream, TelemetryStream) else 0.0
        rt = self.service.runtime(self.session_id)
        return max(t, rt.view.t_sim_s if rt is not None else 0.0)

    def error(
        self, code: str, detail: str = "", *, fatal: bool = False, oldest: int | None = None
    ) -> dict[str, Any]:
        """Envelope ``error`` local com ``seq`` + 1 da sessão (D-19)."""
        payload = WsErrorPayload(
            code=code,
            title=ws_title(code),
            detail=detail[:500],
            fatal=fatal,
            oldest_available_seq=oldest,
        )
        return {
            "v": 1,
            "type": "error",
            "seq": self._allocate_seq(),
            "t_sim_s": self._t_now(),
            "payload": payload.model_dump(mode="json"),
        }

    def _snapshot(self) -> dict[str, Any]:
        last = self.stream.last_run_state
        if last is not None:
            payload = last["payload"]
            t = float(last["t_sim_s"])
        else:
            rt = self.service.runtime(self.session_id)
            payload = {
                "session_id": self.session_id,
                "run_id": None,
                "run_type": None,
                "state": "idle",
                "previous_state": None,
                "phase": None,
                "pull_index": None,
                "pull_count": None,
                "abort_reason": None,
                "progress_pct": None,
                "rpm": 0.0,
                "realtime_factor": None if rt is None else rt.view.realtime_factor,
                "forensic_report_url": None,
            }
            t = self._t_now()
        return {
            "v": 1,
            "type": "run.state",
            "seq": self._allocate_seq(),
            "t_sim_s": t,
            "payload": payload,
        }

    def preamble(self, resume_from_seq: int | None) -> list[dict[str, Any]]:
        """Snapshot de ``run.state``, erros do resume e replay (websocket-telemetry 7)."""
        current = self.stream.seq
        snapshot = self._snapshot()
        out = [snapshot]
        if resume_from_seq is None:
            return out
        stream = self.stream
        if not isinstance(stream, TelemetryStream):
            out.extend(e for e in stream.events_after(resume_from_seq) if e["type"] != "error")
            return out
        plan = stream.replay_buffer.resume(resume_from_seq, current)
        if plan.invalid:
            out.append(
                self.error(
                    "WS_RESUME_INVALID",
                    f"resume_from_seq {resume_from_seq} > seq atual {current}; conexão nova.",
                )
            )
            return out
        if plan.gap_oldest_seq is not None:
            out.append(
                self.error(
                    "WS_RESUME_GAP",
                    f"Eventos depois do seq {resume_from_seq} já saíram do buffer de replay.",
                    oldest=plan.gap_oldest_seq,
                )
            )
        out.extend(plan.events)
        return out

    # ------------------------------------------------------------------ ciclo
    def _attach(self) -> None:
        stream = self.stream
        if isinstance(stream, TelemetryStream):
            stream.attach(self.queue)
        else:  # pragma: no cover - hub sem o TelemetryStream (dyno sem install)
            stream._subs.add(self.queue)  # type: ignore[arg-type]

    def _detach(self) -> None:
        stream = self.stream
        if isinstance(stream, TelemetryStream):
            stream.detach(self.queue)
        else:  # pragma: no cover
            stream._subs.discard(self.queue)

    async def run(self, resume_from_seq: int | None) -> None:
        await self.ws.accept()
        opened = self.clock()
        self._attach()
        log.info("telemetry.ws.open", session_id=self.session_id, resume=resume_from_seq)
        try:
            for envelope in self.preamble(resume_from_seq):
                await self._send(envelope)
            sender = asyncio.create_task(self._send_loop())
            receiver = asyncio.create_task(self._recv_loop())
            _, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in (sender, receiver):
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                    await task
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self._detach()
            self.queue.close()
            with contextlib.suppress(Exception):
                await self.service.release_composites(self.session_id, id(self))
            log.info(
                "telemetry.ws.close",
                session_id=self.session_id,
                code=self.close_code,
                duration_s=round(self.clock() - opened, 3),
                dropped_frames=self.queue.dropped_frames,
                dropped_events=self.queue.dropped_events,
            )

    async def _send(self, envelope: dict[str, Any]) -> None:
        await self.ws.send_text(orjson.dumps(envelope).decode("utf-8"))
        self.sent += 1

    async def close(self, code: int, reason: str = "") -> None:
        if self.close_code is None:
            self.close_code = code
            if self.ws.application_state != WebSocketState.DISCONNECTED:
                with contextlib.suppress(Exception):
                    await self.ws.close(code=code, reason=reason)
        self._closed.set()

    async def _send_loop(self) -> None:
        queue = self.queue
        while True:
            envelope = await queue.next()
            if envelope is None:
                await self.close(1000)
                return
            kind = envelope["type"]
            if kind == "telemetry.frame":
                message = render_frame(
                    envelope,
                    self.subscription,
                    queue,
                    self.fps_meter.tick(float(envelope["t_sim_s"])),
                    self.service.realtime_factor(self.session_id),
                )
                await self._send(message)
                continue
            if kind == "event.knock" and not self.knock_guard.allow(envelope):
                continue
            await self._send(envelope)
            payload = envelope.get("payload") or {}
            if kind == "error" and payload.get("fatal"):
                code = str(payload.get("code"))
                await self.close(CLOSE_CODES.get(code, 1011), code)
                return

    async def _recv_loop(self) -> None:
        last = self.clock()
        while True:
            remaining = self.idle_timeout_s - (self.clock() - last)
            try:
                message = await asyncio.wait_for(self.ws.receive(), max(remaining, 0.0))
            except TimeoutError:
                await self.close(CLOSE_CODES["WS_IDLE_TIMEOUT"], "WS_IDLE_TIMEOUT")
                return
            if message["type"] == "websocket.disconnect":
                self.queue.close()
                return
            last = self.clock()
            raw = message.get("text")
            if raw is None:
                data = message.get("bytes") or b""
                raw = data.decode("utf-8", errors="replace")
            valid = await self.handle(raw)
            if self.limiter.record(valid=valid):
                self.queue.offer(self.error("WS_RATE_LIMITED", "Mensagens em excesso.", fatal=True))
                await self._closed.wait()
                return

    # ------------------------------------------------------------------ mensagens do cliente
    def _local(self, code: str, detail: str = "") -> None:
        self.queue.offer(self.error(code, detail))

    async def handle(self, raw: str) -> bool:
        """Processa uma mensagem; ``False`` se ela é inválida (``WS_MESSAGE_INVALID``)."""
        if len(raw.encode("utf-8")) > MAX_CLIENT_MESSAGE_BYTES:
            self._local("WS_MESSAGE_INVALID", "mensagem acima de 16 kB")
            return False
        try:
            message = WsClientMessage.model_validate(orjson.loads(raw))
        except (orjson.JSONDecodeError, ValidationError, TypeError) as exc:
            self._local("WS_MESSAGE_INVALID", f"{type(exc).__name__}"[:200])
            return False
        if message.type == "control.ping":
            return True
        if message.type == "control.subscribe":
            return await self._subscribe(message.payload)
        return await self._throttle(message.payload)

    async def _subscribe(self, payload: dict[str, Any]) -> bool:
        result = apply_subscribe(
            payload,
            self.subscription,
            self.catalog,
            self.n_cyl,
            spectrum_available=self.service.spectrum_available(self.session_id),
        )
        self.subscription = result.subscription
        valid = True
        for code, detail in result.errors:
            valid = valid and code != "WS_MESSAGE_INVALID"
            self._local(code, detail)
        try:
            await self.service.set_composites(
                self.session_id,
                id(self),
                spectrum=self.subscription.spectrum,
                pressure_trace=self.subscription.trace_cylinder is not None,
            )
        except SimRemapError as exc:
            self._local(exc.error_code, exc.detail)
        if result.fps is not None:
            try:
                await self.service.set_fps(self.session_id, result.fps)
            except SimRemapError as exc:
                self._local(exc.error_code, exc.detail)
        return valid

    async def _throttle(self, payload: dict[str, Any]) -> bool:
        value = payload.get("throttle_pct")
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not 0 <= value <= THROTTLE_MAX_PCT
        ):
            self._local("WS_MESSAGE_INVALID", "throttle_pct deve estar entre 0 e 100")
            return False
        try:
            code = await self.service.throttle(self.session_id, float(value))
        except SimRemapError as exc:
            self._local(exc.error_code, exc.detail)
            return True
        if code is not None:
            self._local(code, "Acelerador bloqueado durante a puxada.")
        return True
