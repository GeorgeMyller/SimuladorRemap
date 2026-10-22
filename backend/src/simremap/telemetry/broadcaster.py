"""Difusão do WebSocket no event loop (tel RF-03, RF-07 a RF-10, RF-23, RF-25; D-05; D-19).

- ``TelemetryStream`` estende o ``SessionStream`` do dyno-bench, instalado no hub
  partilhado (``app.state.dyno_stream_hub``) por ``StreamHub.set_stream_factory``: o ``seq``
  continua a ser atribuído por ele, uma vez por
  envelope publicado, antes de qualquer filtro ou descarte; ``allocate_seq`` dá o ``seq`` dos
  envelopes locais a 1 conexão (``error``, snapshot de ``run.state``), sempre ``+ 1`` no mesmo
  contador; os tipos internos ``telemetry.log_*`` do ``TelemetrySampler`` são desviados para o
  datalogger (``StreamListener``) e nunca chegam aos clientes.
- ``ReplayBuffer``: só ``run.state`` e ``event.*``, últimos 10 s simulados ou 512 envelopes
  (o limite que chegar primeiro); ``resume`` devolve os eventos com ``seq > n`` com o ``seq``
  original, ``WS_RESUME_GAP`` (com ``oldest_available_seq``) ou ``WS_RESUME_INVALID``.
- ``ConnectionQueue``: fila por conexão; frames 8 (descarta o mais antigo e conta
  ``dropped_frames``), eventos 256 (descarta o ``event.knock`` mais antigo e conta
  ``dropped_events``; ``run.state``, ``event.failure``, ``event.limiter`` e ``error`` nunca
  são descartados). A saída respeita a ordem do ``seq`` entre as duas filas. ``offer`` nunca
  bloqueia: o produtor (worker → event loop) não espera pelo socket.
- ``render_frame``: filtro por subscrição perto do socket e ``stats`` da conexão.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import orjson

from simremap.dyno.stream import SessionStream, StreamHub
from simremap.telemetry.channels import COMPOSITE_CHANNELS, ChannelCatalog
from simremap.telemetry.contracts import DEFAULT_CHANNELS, MAX_SUBSCRIBED_CHANNELS
from simremap.telemetry.decimator import FPS_MAX, FPS_MIN
from simremap.telemetry.sampler import LOG_BLOCK, LOG_END, LOG_OPEN

__all__ = [
    "EVENT_QUEUE_SIZE",
    "FRAME_QUEUE_SIZE",
    "INTERNAL_TYPES",
    "KNOCK_MAX_PER_S",
    "REPLAY_MAX_EVENTS",
    "REPLAY_TYPES",
    "REPLAY_WINDOW_S",
    "ClientRateLimiter",
    "ClientSubscription",
    "ConnectionQueue",
    "FpsMeter",
    "KnockRateGuard",
    "ReplayBuffer",
    "ResumePlan",
    "StreamListener",
    "TelemetryStream",
    "TelemetryStreamHub",
    "apply_subscribe",
    "install_stream_hub",
    "render_frame",
]

FRAME_QUEUE_SIZE: Final = 8
EVENT_QUEUE_SIZE: Final = 256
REPLAY_MAX_EVENTS: Final = 512
REPLAY_WINDOW_S: Final = 10.0
KNOCK_MAX_PER_S: Final = 10
INTERNAL_TYPES: Final = frozenset({LOG_OPEN, LOG_BLOCK, LOG_END})
REPLAY_TYPES: Final = frozenset({"run.state", "event.knock", "event.failure", "event.limiter"})
_DROPPABLE: Final = "event.knock"
_CLOSE_TYPE: Final = "__close__"


class StreamListener(Protocol):
    """Datalogger: recebe os tipos internos e os envelopes públicos já com ``seq``."""

    def on_internal(self, session_id: str, envelope: dict[str, Any]) -> None: ...
    def on_public(self, session_id: str, envelope: dict[str, Any]) -> None: ...
    def on_close(self, session_id: str) -> None: ...


# --------------------------------------------------------------------------- replay


@dataclass(frozen=True, slots=True)
class ResumePlan:
    events: list[dict[str, Any]]
    gap_oldest_seq: int | None = None  # WS_RESUME_GAP
    invalid: bool = False  # WS_RESUME_INVALID


class ReplayBuffer:
    """Últimos 10 s simulados ou 512 eventos (o que chegar primeiro), sem frames."""

    def __init__(
        self, max_events: int = REPLAY_MAX_EVENTS, window_s: float = REPLAY_WINDOW_S
    ) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self.items: deque[dict[str, Any]] = deque()
        self.evicted_max_seq = -1
        self.latest_t = 0.0

    def append(self, envelope: dict[str, Any]) -> None:
        self.items.append(envelope)
        self.observe(float(envelope.get("t_sim_s", 0.0)))
        while len(self.items) > self.max_events:
            self._evict()

    def observe(self, t_sim_s: float) -> None:
        """Avança o tempo simulado (frames incluídos) e descarta o que saiu da janela."""
        self.latest_t = max(self.latest_t, t_sim_s)
        limit = self.latest_t - self.window_s
        while self.items and float(self.items[0].get("t_sim_s", 0.0)) < limit:
            self._evict()

    def _evict(self) -> None:
        old = self.items.popleft()
        self.evicted_max_seq = max(self.evicted_max_seq, int(old["seq"]))

    @property
    def oldest_seq(self) -> int | None:
        return int(self.items[0]["seq"]) if self.items else None

    def resume(self, after_seq: int, current_seq: int) -> ResumePlan:
        if after_seq > current_seq:
            return ResumePlan([], invalid=True)
        events = [e for e in self.items if int(e["seq"]) > after_seq]
        if self.evicted_max_seq > after_seq:
            oldest = self.oldest_seq
            return ResumePlan(events, gap_oldest_seq=current_seq + 1 if oldest is None else oldest)
        return ResumePlan(events)


# --------------------------------------------------------------------------- stream


class TelemetryStream(SessionStream):
    """``SessionStream`` com desvio dos tipos internos, replay de 10 s e ``seq`` local."""

    def __init__(self, session_id: str, listener: StreamListener | None = None) -> None:
        super().__init__(session_id)
        self.listener = listener
        self.replay_buffer = ReplayBuffer()
        self.connections = 0

    def publish(self, raw: bytes | dict[str, Any]) -> dict[str, Any] | None:
        envelope = orjson.loads(raw) if isinstance(raw, bytes | bytearray) else raw
        kind = envelope.get("type")
        if kind in INTERNAL_TYPES:
            if self.listener is not None:
                self.listener.on_internal(self.session_id, envelope)
            return None
        out = super().publish(envelope)
        if out is None:
            return None
        if out["type"] in REPLAY_TYPES:
            self.replay_buffer.append(out)
        else:
            self.replay_buffer.observe(out["t_sim_s"])
        if self.listener is not None and out["type"] != "telemetry.frame":
            self.listener.on_public(self.session_id, out)
        return out

    def allocate_seq(self) -> int:
        """Próximo ``seq`` da sessão para um envelope local a 1 conexão."""
        self.seq += 1
        return self.seq

    def attach(self, queue: ConnectionQueue) -> None:
        if self.closed:
            queue.offer({"type": _CLOSE_TYPE})
        self._subs.add(queue)  # type: ignore[arg-type]

    def detach(self, queue: ConnectionQueue) -> None:
        self._subs.discard(queue)

    def close(self) -> None:
        super().close()
        if self.listener is not None:
            self.listener.on_close(self.session_id)


class TelemetryStreamHub(StreamHub):
    """``StreamHub`` que cria ``TelemetryStream`` (hub próprio, ex.: testes sem o dyno)."""

    def __init__(self, listener: StreamListener | None = None) -> None:
        super().__init__(lambda session_id: TelemetryStream(session_id, self.listener))
        self.listener = listener


def install_stream_hub(hub: StreamHub, listener: StreamListener) -> StreamHub:
    """Liga o ``TelemetryStream`` ao hub do dyno-bench pelo ponto ``set_stream_factory``.

    O objeto partilhado (``app.state.dyno_stream_hub``) não muda de classe: só as sessões
    criadas depois passam a usar ``TelemetryStream`` com o ``listener`` do datalogger.
    """
    if isinstance(hub, TelemetryStreamHub):
        hub.listener = listener
        return hub
    hub.set_stream_factory(lambda session_id: TelemetryStream(session_id, listener))
    return hub


# --------------------------------------------------------------------------- conexão


class ConnectionQueue:
    """Filas de uma conexão (frames 8 e eventos 256), saída na ordem do ``seq``."""

    def __init__(self) -> None:
        self.frames: deque[dict[str, Any]] = deque()
        self.events: deque[dict[str, Any]] = deque()
        self.dropped_frames = 0
        self.dropped_events = 0
        self.closed = False
        self._wake = asyncio.Event()

    def offer(self, envelope: dict[str, Any]) -> None:
        kind = envelope.get("type")
        if kind == _CLOSE_TYPE:
            self.closed = True
        elif kind == "telemetry.frame":
            if len(self.frames) >= FRAME_QUEUE_SIZE:
                self.frames.popleft()
                self.dropped_frames += 1
            self.frames.append(envelope)
        else:
            if len(self.events) >= EVENT_QUEUE_SIZE:
                for i, queued in enumerate(self.events):
                    if queued.get("type") == _DROPPABLE:
                        del self.events[i]
                        self.dropped_events += 1
                        break
            self.events.append(envelope)
        self._wake.set()

    def __len__(self) -> int:
        return len(self.frames) + len(self.events)

    def pop(self) -> dict[str, Any] | None:
        """Próximo envelope pela ordem do ``seq`` (sem esperar)."""
        if self.events and self.frames:
            if int(self.frames[0]["seq"]) < int(self.events[0]["seq"]):
                return self.frames.popleft()
            return self.events.popleft()
        if self.events:
            return self.events.popleft()
        if self.frames:
            return self.frames.popleft()
        return None

    async def next(self) -> dict[str, Any] | None:
        """Espera o próximo envelope; ``None`` com a fila fechada e vazia."""
        while True:
            item = self.pop()
            if item is not None:
                return item
            if self.closed:
                return None
            self._wake.clear()
            await self._wake.wait()

    def close(self) -> None:
        self.closed = True
        self._wake.set()


@dataclass(slots=True)
class ClientSubscription:
    """Subscrição de uma conexão (o padrão antes do 1.º ``control.subscribe``)."""

    channels: tuple[str, ...] = DEFAULT_CHANNELS
    spectrum: bool = False
    trace_cylinder: int | None = None


@dataclass(slots=True)
class SubscribeResult:
    subscription: ClientSubscription
    fps: int | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value)


def apply_subscribe(
    payload: dict[str, Any],
    current: ClientSubscription,
    catalog: ChannelCatalog | None,
    n_cyl: int,
    *,
    spectrum_available: bool = True,
) -> SubscribeResult:
    """Aplica ``control.subscribe``: partes inválidas viram erros, as válidas valem (EC-06)."""
    errors: list[tuple[str, str]] = []
    channels = payload.get("channels")
    if not isinstance(channels, list) or not all(isinstance(c, str) for c in channels):
        return SubscribeResult(current, errors=[("WS_MESSAGE_INVALID", "channels deve ser lista")])
    if not 1 <= len(channels) <= MAX_SUBSCRIBED_CHANNELS:
        return SubscribeResult(
            current, errors=[("WS_MESSAGE_INVALID", "channels deve ter 1 a 128 nomes")]
        )
    names = list(dict.fromkeys(channels))
    unknown = catalog.unknown(names) if catalog is not None else []
    valid = [n for n in names if n not in unknown]
    if unknown:
        errors.append(("WS_UNKNOWN_CHANNEL", ", ".join(unknown)[:500]))
    scalars = tuple(n for n in valid if n not in COMPOSITE_CHANNELS)
    spectrum = bool(payload.get("spectrum", False)) or "knock_spectrum" in valid
    trace: int | None = 1 if "cyl_pressure_trace" in valid else None
    raw_trace = payload.get("pressure_trace")
    if isinstance(raw_trace, dict):
        cylinder = _int(raw_trace.get("cylinder"))
        if cylinder is None:
            errors.append(("WS_MESSAGE_INVALID", "pressure_trace.cylinder deve ser inteiro"))
        elif not 1 <= cylinder <= n_cyl:
            errors.append(("WS_CYLINDER_OUT_OF_RANGE", f"cilindro {cylinder} fora de 1..{n_cyl}"))
        else:
            trace = cylinder
    elif raw_trace is not None:
        errors.append(("WS_MESSAGE_INVALID", "pressure_trace deve ser objeto ou null"))
    fps: int | None = None
    if "fps" in payload:
        value = _int(payload.get("fps"))
        if value is None or not FPS_MIN <= value <= FPS_MAX:
            errors.append(("WS_FPS_OUT_OF_RANGE", f"fps {payload.get('fps')!r} fora de 30–60"))
        else:
            fps = value
    if spectrum and not spectrum_available:
        errors.append(("SPECTRUM_UNAVAILABLE", "gerador de espectro indisponível nesta sessão"))
        spectrum = False
    # Sem nenhum canal escalar válido, os canais anteriores continuam ativos.
    new = ClientSubscription(scalars or current.channels, spectrum, trace)
    return SubscribeResult(new, fps=fps, errors=errors)


class KnockRateGuard:
    """Verificação do limite de 10 ``event.knock``/s por cilindro (``t_sim_s``; D-17)."""

    def __init__(self, max_per_s: int = KNOCK_MAX_PER_S) -> None:
        self.max_per_s = max_per_s
        self._times: dict[int, deque[float]] = {}
        self.suppressed = 0

    def allow(self, envelope: dict[str, Any]) -> bool:
        payload = envelope.get("payload") or {}
        cylinder = int(payload.get("cylinder", 0))
        t = float(envelope.get("t_sim_s", 0.0))
        times = self._times.setdefault(cylinder, deque())
        while times and times[0] <= t - 1.0:
            times.popleft()
        if len(times) >= self.max_per_s:
            self.suppressed += 1
            return False
        times.append(t)
        return True


class FpsMeter:
    """Frames entregues no último segundo simulado (``stats.fps_actual``)."""

    def __init__(self) -> None:
        self._times: deque[float] = deque()

    def tick(self, t_sim_s: float) -> float:
        times = self._times
        times.append(t_sim_s)
        while times and times[0] <= t_sim_s - 1.0:
            times.popleft()
        return float(len(times))


class ClientRateLimiter:
    """> 20 mensagens inválidas em 10 s ou > 100 mensagens/s ⇒ abuso (RF-24; EC-18)."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        max_invalid: int = 20,
        invalid_window_s: float = 10.0,
        max_per_s: int = 100,
    ) -> None:
        self.clock = clock
        self.max_invalid = max_invalid
        self.invalid_window_s = invalid_window_s
        self.max_per_s = max_per_s
        self._all: deque[float] = deque()
        self._invalid: deque[float] = deque()

    def record(self, *, valid: bool) -> bool:
        """Regista uma mensagem; ``True`` se o limite foi ultrapassado."""
        now = self.clock()
        self._all.append(now)
        while self._all and self._all[0] <= now - 1.0:
            self._all.popleft()
        if not valid:
            self._invalid.append(now)
        while self._invalid and self._invalid[0] <= now - self.invalid_window_s:
            self._invalid.popleft()
        return len(self._all) > self.max_per_s or len(self._invalid) > self.max_invalid


def render_frame(
    envelope: dict[str, Any],
    subscription: ClientSubscription,
    queue: ConnectionQueue,
    fps_actual: float,
    real_time_factor: float | None,
) -> dict[str, Any]:
    """``telemetry.frame`` da conexão: canais subscritos, compostos pedidos e ``stats``."""
    source = envelope["payload"]
    all_channels: dict[str, Any] = source.get("channels") or {}
    channels = {n: all_channels[n] for n in subscription.channels if n in all_channels}
    trace = None
    cylinder = subscription.trace_cylinder
    if cylinder is not None:
        traces = source.get("_traces") or {}
        raw = traces.get(str(cylinder))
        if raw is not None:
            trace = {"cylinder": cylinder, "crank_deg": raw["crank_deg"], "p_bar": raw["p_bar"]}
    stats = dict(source.get("stats") or {})
    rtf = stats.get("real_time_factor")
    stats.update(
        fps_actual=fps_actual,
        dropped_frames=queue.dropped_frames,
        dropped_events=queue.dropped_events,
        real_time_factor=rtf if rtf is not None else real_time_factor,
    )
    stats.setdefault("tick", 0)
    return {
        "v": 1,
        "type": "telemetry.frame",
        "seq": envelope["seq"],
        "t_sim_s": envelope["t_sim_s"],
        "payload": {
            "session_id": source.get("session_id"),
            "run_id": source.get("run_id"),
            "frame_index": source.get("frame_index"),
            "window_ticks": source.get("window_ticks"),
            "channels": channels,
            "knock_spectrum": source.get("knock_spectrum") if subscription.spectrum else None,
            "cyl_pressure_trace": trace,
            "stats": stats,
        },
    }
