"""Ponto de assinatura das saídas do laço no event loop (consumido pelo telemetry-datalogger).

O worker publica envelopes sem ``seq``; o ``SessionStream`` de cada sessão atribui o
``seq`` (contador único por sessão, a começar em 0, partilhado por todos os tipos;
websocket-telemetry 2.1) e entrega-os aos assinantes. Regras de backpressure da seção 6:

- a saída de cada assinante respeita a ordem do ``seq`` entre frames e eventos;
- cada assinante tem uma fila de frames (8, descarta o mais antigo e conta
  ``dropped_frames``) e uma fila de eventos (256, descarta o ``event.knock`` mais antigo
  e conta ``dropped_events``); ``run.state``, ``event.failure``, ``event.limiter`` e
  ``error`` nunca são descartados;
- o último ``run.state`` fica disponível em ``last_run_state`` (snapshot da ligação) e um
  buffer de replay guarda os últimos 512 eventos (sem frames) para ``resume_from_seq``.

Uso (telemetry-datalogger)::

    hub: StreamHub = app.state.dyno_stream_hub
    stream = hub.get(session_id)             # None se a sessão não existe
    async with stream.subscribe() as sub:
        async for envelope in sub:           # dict {"v", "type", "seq", "t_sim_s", "payload"}
            ...
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Final

import orjson

__all__ = [
    "EVENT_QUEUE_SIZE",
    "FRAME_QUEUE_SIZE",
    "PUBLIC_TYPES",
    "REPLAY_SIZE",
    "SessionStream",
    "StreamFactory",
    "StreamHub",
    "Subscription",
]

FRAME_QUEUE_SIZE: Final = 8
EVENT_QUEUE_SIZE: Final = 256
REPLAY_SIZE: Final = 512
PUBLIC_TYPES: Final = frozenset(
    {"telemetry.frame", "run.state", "event.knock", "event.failure", "event.limiter", "error"}
)
"""Tipos de envelope do contrato WS (os restantes são internos ao dyno-bench)."""
_DROPPABLE_EVENT: Final = "event.knock"
_CLOSE: Final[dict[str, Any]] = {"type": "__close__"}


@dataclass(slots=True, eq=False)
class Subscription:
    """Fila de um assinante (frames e eventos separados)."""

    frames: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=FRAME_QUEUE_SIZE))
    events: deque[dict[str, Any]] = field(default_factory=deque)
    dropped_frames: int = 0
    dropped_events: int = 0
    closed: bool = False
    _wake: asyncio.Event = field(default_factory=asyncio.Event)

    def offer(self, envelope: dict[str, Any]) -> None:
        if envelope is _CLOSE:
            self.closed = True
        elif envelope["type"] == "telemetry.frame":
            if len(self.frames) == FRAME_QUEUE_SIZE:
                self.dropped_frames += 1
            self.frames.append(envelope)
        else:
            if len(self.events) >= EVENT_QUEUE_SIZE:
                for i, queued in enumerate(self.events):
                    if queued["type"] == _DROPPABLE_EVENT:
                        del self.events[i]
                        self.dropped_events += 1
                        break
            self.events.append(envelope)
        self._wake.set()

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> dict[str, Any]:
        while True:
            item = self.get_nowait()
            if item is not None:
                return item
            if self.closed:
                raise StopAsyncIteration
            self._wake.clear()
            await self._wake.wait()

    def get_nowait(self) -> dict[str, Any] | None:
        """Próximo envelope na ordem do ``seq`` entre as duas filas (sem esperar).

        Um evento nunca ultrapassa um frame já enfileirado com ``seq`` menor: os clientes
        descartam envelopes com ``seq`` ≤ o último aceite.
        """
        events, frames = self.events, self.frames
        if events and frames:
            if int(frames[0]["seq"]) < int(events[0]["seq"]):
                return frames.popleft()
            return events.popleft()
        if events:
            return events.popleft()
        if frames:
            return frames.popleft()
        return None


class SessionStream:
    """Saídas públicas de uma sessão com ``seq`` atribuído."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.seq = -1
        self.last_run_state: dict[str, Any] | None = None
        self.replay: deque[dict[str, Any]] = deque(maxlen=REPLAY_SIZE)
        self._subs: set[Subscription] = set()
        self.closed = False

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def publish(self, raw: bytes | dict[str, Any]) -> dict[str, Any] | None:
        """Atribui ``seq`` e entrega; tipos internos e sessões fechadas são ignorados."""
        envelope = orjson.loads(raw) if isinstance(raw, bytes | bytearray) else dict(raw)
        if self.closed or envelope.get("type") not in PUBLIC_TYPES:
            return None
        self.seq += 1
        out = {
            "v": 1,
            "type": envelope["type"],
            "seq": self.seq,
            "t_sim_s": float(envelope.get("t_sim_s", 0.0)),
            "payload": envelope.get("payload", {}),
        }
        if out["type"] == "run.state":
            self.last_run_state = out
        if out["type"] != "telemetry.frame":
            self.replay.append(out)
        for sub in tuple(self._subs):
            sub.offer(out)
        return out

    def events_after(self, seq: int) -> list[dict[str, Any]]:
        """Eventos do buffer de replay com ``seq`` maior que ``seq``."""
        return [e for e in self.replay if e["seq"] > seq]

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscription]:
        sub = Subscription()
        if self.closed:
            sub.closed = True
        self._subs.add(sub)
        try:
            yield sub
        finally:
            self._subs.discard(sub)

    def close(self) -> None:
        self.closed = True
        for sub in tuple(self._subs):
            sub.offer(_CLOSE)


StreamFactory = Callable[[str], SessionStream]
"""Cria o ``SessionStream`` de uma sessão nova (``session_id`` → stream)."""


class StreamHub:
    """``session_id`` → ``SessionStream`` (``app.state.dyno_stream_hub``).

    Ponto de ligação explícito para outros componentes: ``set_stream_factory`` troca a
    classe dos streams das sessões criadas a partir daí (a telemetria instala o
    ``TelemetryStream``, subclasse de ``SessionStream``), sem trocar o objeto partilhado.
    """

    def __init__(self, stream_factory: StreamFactory | None = None) -> None:
        self._streams: dict[str, SessionStream] = {}
        self._factory: StreamFactory = stream_factory or SessionStream

    @property
    def stream_factory(self) -> StreamFactory:
        return self._factory

    def set_stream_factory(self, factory: StreamFactory | None) -> None:
        """Fábrica dos streams das sessões novas (``None`` volta ao ``SessionStream``)."""
        self._factory = factory or SessionStream

    def create(self, session_id: str) -> SessionStream:
        stream = self._factory(session_id)
        if not isinstance(stream, SessionStream):
            raise TypeError("a fábrica de streams deve devolver um SessionStream")
        self._streams[session_id] = stream
        return stream

    def get(self, session_id: str) -> SessionStream | None:
        return self._streams.get(session_id)

    def close(self, session_id: str) -> None:
        stream = self._streams.pop(session_id, None)
        if stream is not None:
            stream.close()

    def close_all(self) -> None:
        for session_id in list(self._streams):
            with contextlib.suppress(Exception):
                self.close(session_id)
