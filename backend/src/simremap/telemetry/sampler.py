"""``TelemetrySampler``: amostrador da telemetria no worker (tel RF-05, RF-06, RF-14, RF-20,
RF-21, RF-23; D-BUS-06; simulation-bus 3.5).

Implementa o ``TickSampler`` do dyno-bench (``on_tick``/``set_fps``/``drain``) e é
instalado por ``"simremap.telemetry.sampler:TelemetrySampler"`` no campo ``sampler`` do
``DynoInitPayload``. Construção: ``(session_id, sim_hz, fps, n_cyl, afr_stoich)``.

A cada tick:

1. extrai 1 linha com todos os canais escalares do catálogo (``channels.build_catalog``),
   sem objetos Pydantic novos (NaN = ausente);
2. acumula a linha no ``FrameDecimator``; no último tick da janela publica o
   ``telemetry.frame`` com todos os canais arredondados aos decimais do catálogo (o filtro por
   subscrição corre no event loop), o espectro do dano (``bind_spectrum``, chamado pelo laço
   com ``DamageModel.spectrum_frame``) e, a no máximo 10 Hz, o último traço de pressão de
   cada cilindro em ``payload._traces`` (campo interno, retirado antes do envio); espectro e
   traço só são calculados enquanto ``configure`` não os desliga (a telemetria liga-os com
   ≥ 1 conexão a pedi-los);
3. durante uma puxada (``TickRecord.run_id`` não nulo, de ``arming`` ao estado terminal)
   grava a linha no log colunar ``float32`` em blocos de 250 ms, enviados ao event loop pela
   faixa crítica (sem descarte): ``telemetry.log_open``, ``telemetry.log_block`` (colunas em
   base64 little-endian) e ``telemetry.log_end``. Acima de 300 s o log para de gravar
   amostras e marca ``truncated`` (EC-14).

O ``seq`` dos envelopes é atribuído no event loop; o worker nunca bloqueia.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import orjson

from simremap.core.worker.logbridge import worker_log
from simremap.telemetry.channels import ChannelCatalog, build_catalog
from simremap.telemetry.decimator import ClosedFrame, FrameDecimator
from simremap.telemetry.spectrum import (
    SpectrumSource,
    spectrum_payload,
    trace_every_n_frames,
    trace_payload,
)

__all__ = [
    "LOG_BLOCK",
    "LOG_BLOCK_S",
    "LOG_END",
    "LOG_MAX_S",
    "LOG_OPEN",
    "SAMPLER_SPEC",
    "TelemetrySampler",
    "decode_block",
]

SAMPLER_SPEC: Final = "simremap.telemetry.sampler:TelemetrySampler"
LOG_OPEN: Final = "telemetry.log_open"
LOG_BLOCK: Final = "telemetry.log_block"
LOG_END: Final = "telemetry.log_end"
LOG_BLOCK_S: Final = 0.25
LOG_MAX_S: Final = 300.0
NAN32: Final = np.uint32(0x7FC00000)


def _envelope(kind: str, t_sim_s: float, payload: dict[str, Any]) -> bytes:
    return orjson.dumps({"v": 1, "type": kind, "t_sim_s": t_sim_s, "payload": payload})


def _b64(array: np.ndarray) -> str:
    return base64.b64encode(array.tobytes()).decode("ascii")


def decode_block(payload: dict[str, Any], n_channels: int) -> tuple[np.ndarray, np.ndarray]:
    """``telemetry.log_block`` → (``t_sim_s`` float64 [n], dados float32 [n, n_channels])."""
    n = int(payload["n"])
    t = np.frombuffer(base64.b64decode(payload["t_sim_s"]), dtype="<f8")
    data = np.frombuffer(base64.b64decode(payload["data"]), dtype="<f4")
    if t.size != n or data.size != n * n_channels:
        raise ValueError("bloco de log com tamanho inconsistente")
    return t.astype(np.float64), data.reshape(n, n_channels).astype(np.float32)


@dataclass(slots=True)
class _OpenLog:
    run_id: str
    start_tick: int
    block_rows: int
    max_samples: int
    n_channels: int
    t_block: np.ndarray = field(init=False)
    block: np.ndarray = field(init=False)
    rows: int = 0
    n_samples: int = 0
    flushed: int = 0
    truncated: bool = False
    pulls: list[dict[str, Any]] = field(default_factory=list)
    pull_start: int | None = None
    pull_index: int | None = None
    non_finite_logged: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.t_block = np.empty(self.block_rows, dtype="<f8")
        self.block = np.empty((self.block_rows, self.n_channels), dtype="<f4")


class TelemetrySampler:
    """Amostrador de frames e do log à taxa total (``TickSampler`` do dyno-bench)."""

    def __init__(
        self, session_id: str, sim_hz: int, fps: int, n_cyl: int, afr_stoich: float
    ) -> None:
        self.session_id = session_id
        self.sim_hz = int(sim_hz)
        self.n_cyl = int(n_cyl)
        self.afr_stoich = float(afr_stoich)
        self._initial_fps = FrameDecimator.clamp_fps(fps)
        self._pending_fps: int | None = None
        self.catalog: ChannelCatalog | None = None
        self.decimator: FrameDecimator | None = None
        self.spectrum_source: SpectrumSource | None = None
        self._spectrum_failed = False
        # None = ligado (padrão sem telemetry.config); False/True = pedido das conexões.
        self.spectrum_enabled: bool | None = None
        self.trace_enabled: bool | None = None
        self._outputs: list[bytes] = []
        self._log: _OpenLog | None = None
        self._health_ids: list[str] = []
        self._scale: np.ndarray = np.ones(0)
        self._nullable: np.ndarray = np.zeros(0, dtype=bool)
        self._last_events: dict[int, Any] = {}
        self._frames = 0
        self._run_id: str | None = None
        self._pending_spectrum: tuple[bool, dict[str, Any] | None] = (False, None)
        self._pending_traces: dict[str, dict[str, list[Any]]] | None = None
        window = max(1, self.sim_hz // self._initial_fps)
        self._spectrum_tick = max(1, window // 2)
        self._trace_tick = max(1, window // 4)

    # ------------------------------------------------------------------ configuração
    @property
    def fps(self) -> int:
        if self.decimator is None:
            return self._pending_fps or self._initial_fps
        return self.decimator.fps

    def set_fps(self, fps: int) -> None:
        """Nova taxa da sessão a partir da próxima fronteira de frame (30..60)."""
        if self.decimator is None:
            self._initial_fps = FrameDecimator.clamp_fps(fps)
        else:
            self.decimator.set_fps(fps)

    def configure(
        self, *, spectrum: bool | None = None, pressure_trace: bool | None = None
    ) -> None:
        """``telemetry.config``: calcula espectro/traço só quando alguma conexão os pede.

        ``None`` mantém o valor atual. O espectro custa ~30 µs por frame; desligado, o
        ``knock_spectrum`` do frame sai ``null`` e nada é calculado.
        """
        if spectrum is not None:
            self.spectrum_enabled = bool(spectrum)
            if not spectrum:
                self._pending_spectrum = (False, None)
        if pressure_trace is not None:
            self.trace_enabled = bool(pressure_trace)
            if not pressure_trace:
                self._pending_traces = None

    def bind_spectrum(self, source: SpectrumSource | None) -> None:
        """Liga o gerador do espectro do dano (``DamageModel.spectrum_frame``)."""
        self.spectrum_source = source
        self._spectrum_failed = False

    def _setup(self, has_turbo: bool) -> ChannelCatalog:
        catalog = build_catalog(self.n_cyl, has_turbo)
        self.catalog = catalog
        self.decimator = FrameDecimator(self.sim_hz, self._initial_fps, catalog.agg)
        ids = [
            f"{kind}:{k}" for kind in ("piston", "rod", "valves") for k in range(1, 1 + self.n_cyl)
        ]
        ids += ["head_gasket", "bearings"]
        if has_turbo:
            ids.append("turbo:turbine")
        self._health_ids = ids
        self._scale = np.power(10.0, catalog.decimals.astype(np.float64))
        self._nullable = np.array([c.nullable for c in catalog.channels], dtype=bool)
        return catalog

    # ------------------------------------------------------------------ linha do tick
    def row(self, rec: Any) -> list[float]:
        """Valores de todos os canais do catálogo no tick (ordem do catálogo; NaN = ausente)."""
        nan = math.nan
        s = rec.sensors
        st = rec.state
        cmd = rec.commands
        status = rec.ecu.status
        lam_cyl = st.lambda_cyl
        lam_ok = [v for v in lam_cyl if v is not None and not math.isnan(v)]
        lam = math.fsum(lam_ok) / len(lam_ok) if lam_ok else nan
        map_kpa = s.map_kpa
        baro = s.baro_kpa
        row: list[float] = [
            st.rpm,
            map_kpa,
            baro,
            (map_kpa - baro) / 100.0,
            lam,
            s.lambda_measured,
            lam * self.afr_stoich,
        ]
        row.extend([nan if v is None else v for v in lam_cyl])
        row.extend(cmd.ignition_advance_deg)
        row.extend(s.knock_sensor_v)
        row.extend(s.knock_intensity)
        retard = status.knock_retard_deg
        row.append(max(retard) if retard else 0.0)
        row.extend(retard)
        peaks = [p / 100.0 for p in st.p_max_kpa]
        row.extend(peaks)
        row.append(max(peaks) if peaks else nan)
        egt = s.egt_c
        row.extend(egt)
        row.append(max(egt) if egt else nan)
        turbo = s.turbo_rpm
        row.extend(
            (
                s.egt_collector_c,
                s.iat_c,
                s.ect_c,
                s.oil_temp_c,
                nan if turbo is None else turbo,
                nan if turbo is None else cmd.wastegate_duty_pct,
                status.inj_duty_pct,
            )
        )
        row.extend(cmd.injector_pw_ms)
        request = status.torque_request_nm
        pops = 0
        for event in st.events:
            self._last_events[event.cylinder] = event
            if event.pop_event:
                pops += 1
        row.extend(
            (
                st.torque_nm,
                st.power_kw,
                st.whp,
                s.tps_pct,
                rec.load.pedal_pct,
                status.load_pct,
                nan if request is None else request,
                status.lambda_target,
                status.boost_target_kpa,
                1.0 if any(cmd.fuel_cut) else 0.0,
                1.0 if any(cmd.spark_cut) else 0.0,
                float(pops),
                rec.roller_speed_kmh,
            )
        )
        health = {c.component_id: c.health for c in rec.damage.components}
        values = [100.0 * health[i] if i in health else nan for i in self._health_ids]
        row.extend(values)
        row.append(100.0 * min(health.values()) if health else nan)
        rtf = rec.real_time_factor
        row.append(nan if rtf is None else rtf)
        ethanol = s.ethanol_pct
        row.extend(
            (
                s.cam_intake_deg,
                s.cam_exhaust_deg,
                cmd.vvt_intake_target_deg,
                cmd.vvt_exhaust_target_deg,
                nan if ethanol is None else ethanol,
            )
        )
        return row

    # ------------------------------------------------------------------ TickSampler
    def on_tick(self, rec: Any) -> None:
        catalog = self.catalog
        if catalog is None:
            has_turbo = any(c.component_id == "turbo:turbine" for c in rec.damage.components)
            catalog = self._setup(has_turbo or rec.sensors.turbo_rpm is not None)
        decimator = self.decimator
        assert decimator is not None  # noqa: S101 - criado em _setup
        values = np.array(self.row(rec), dtype=np.float64)
        finite = np.isfinite(values)
        if not finite.all():  # EC-17: infinito vira NaN (null no frame, NaN no log)
            values[~finite] = np.nan
        run_id = rec.run_id
        if run_id != self._run_id:
            if self._log is not None:
                self.close_log()
            if run_id is not None:
                self.open_log(run_id, rec.tick, rec.t_sim_s)
            self._run_id = run_id
        log = self._log
        if log is not None:
            self._record(log, rec.t_sim_s, values)
        source = getattr(rec, "spectrum_source", None)
        if source is not None and source is not self.spectrum_source:
            self.bind_spectrum(source)
        closed = decimator.push(rec.tick, rec.t_sim_s, values)
        if closed is not None:
            self._emit_frame(closed, run_id)
            return
        # O trabalho pesado do frame é repartido por ticks diferentes da janela (RNF-01):
        # traço de pressão a 1/4 e espectro a 1/2 da janela; o fecho só agrega e serializa.
        n = decimator.window_ticks
        if (
            n == self._trace_tick
            and self.trace_enabled is not False
            and self._frames % trace_every_n_frames(decimator.fps) == 0
        ):
            self._pending_traces = self._traces()
        if n == self._spectrum_tick and self.spectrum_enabled is not False:
            self._pending_spectrum = (True, self._spectrum(rec.t_sim_s))

    def drain(self) -> list[bytes]:
        out, self._outputs = self._outputs, []
        return out

    # ------------------------------------------------------------------ frames
    def _emit_frame(self, closed: ClosedFrame, run_id: str | None) -> None:
        catalog = self.catalog
        assert catalog is not None  # noqa: S101
        values = closed.values
        ready, spectrum = self._pending_spectrum
        if not ready:
            spectrum = self._spectrum(closed.t_sim_s)
        self._pending_spectrum = (False, None)
        # Arredondamento aos decimais do catálogo (só no WS); NaN sai como null no orjson.
        rounded = np.round(values * self._scale) / self._scale
        channels = dict(zip(catalog.names, rounded.tolist(), strict=True))
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "run_id": run_id,
            "frame_index": closed.frame_index,
            "window_ticks": closed.window_ticks,
            "channels": channels,
            "knock_spectrum": spectrum,
            "cyl_pressure_trace": None,
            "stats": {
                "fps_actual": float(closed.fps),
                "dropped_frames": 0,
                "dropped_events": 0,
                "real_time_factor": None,
                "tick": closed.tick,
            },
        }
        if self.trace_enabled is not False and self._frames % trace_every_n_frames(closed.fps) == 0:
            traces = self._pending_traces if self._pending_traces is not None else self._traces()
            if traces:
                payload["_traces"] = traces
        self._pending_traces = None
        self._frames += 1
        self._outputs.append(_envelope("telemetry.frame", closed.t_sim_s, payload))

    def _traces(self) -> dict[str, dict[str, list[Any]]]:
        return {
            str(cyl): trace_payload(event.theta_start_deg, event.pressure_kpa)
            for cyl, event in sorted(self._last_events.items())
        }

    def _spectrum(self, t_sim_s: float) -> dict[str, Any] | None:
        source = self.spectrum_source
        if source is None or self._spectrum_failed or self.spectrum_enabled is False:
            return None
        try:
            return spectrum_payload(source(t_sim_s))
        except Exception as exc:  # o espectro nunca derruba o laço
            self._spectrum_failed = True
            worker_log().warning(
                "telemetry.spectrum_failed", detail=f"{type(exc).__name__}: {exc}"[:200]
            )
            return None

    # ------------------------------------------------------------------ log da puxada
    def open_log(self, run_id: str, start_tick: int, t_sim_s: float = 0.0) -> None:
        """Abre o log colunar da puxada (1.º tick com ``run_id``)."""
        catalog = self.catalog
        assert catalog is not None  # noqa: S101
        if self._log is not None:
            self.close_log()
        block_rows = max(1, round(LOG_BLOCK_S * self.sim_hz))
        self._log = _OpenLog(
            run_id=run_id,
            start_tick=start_tick,
            block_rows=block_rows,
            max_samples=round(LOG_MAX_S * self.sim_hz),
            n_channels=len(catalog),
        )
        self._run_id = run_id
        self._outputs.append(
            _envelope(
                LOG_OPEN,
                t_sim_s,
                {
                    "run_id": run_id,
                    "session_id": self.session_id,
                    "start_tick": start_tick,
                    "sim_hz": self.sim_hz,
                    "n_cyl": self.n_cyl,
                    "has_turbo": catalog.has_turbo,
                    "channels": list(catalog.names),
                },
            )
        )

    def mark_pull(self, pull_index: int, state: str = "completed") -> None:
        """Começa o segmento ``pull_index`` na amostra atual (fecha o anterior com ``state``)."""
        log = self._log
        if log is None:
            return
        self._end_pull(log, state)
        log.pull_start = log.n_samples
        log.pull_index = int(pull_index)

    @staticmethod
    def _end_pull(log: _OpenLog, state: str) -> None:
        if log.pull_start is not None and log.pull_index is not None:
            log.pulls.append(
                {
                    "pull_index": log.pull_index,
                    "start_index": log.pull_start,
                    "end_index": log.n_samples,
                    "state": state,
                }
            )
        log.pull_start = None
        log.pull_index = None

    def _record(self, log: _OpenLog, t_sim_s: float, values: np.ndarray) -> None:
        if log.n_samples >= log.max_samples:
            log.truncated = True
            return
        r = log.rows
        log.t_block[r] = t_sim_s
        log.block[r] = values
        log.rows = r + 1
        log.n_samples += 1
        if log.rows == log.block_rows:
            self._flush(log)

    def _flush(self, log: _OpenLog) -> None:
        n = log.rows
        if n == 0:
            return
        block = log.block[:n]
        nan_mask = np.isnan(block)
        if nan_mask.any():
            bits = block.view(np.uint32)
            bits[nan_mask] = NAN32  # NaN quiet canónico 0x7FC00000
            bad = np.flatnonzero(nan_mask.any(axis=0) & ~self._nullable)
            for col in bad.tolist():
                if col not in log.non_finite_logged:
                    log.non_finite_logged.add(col)
                    worker_log().warning(
                        "telemetry.non_finite",
                        run_id=log.run_id,
                        channel=self.catalog.names[col] if self.catalog else str(col),
                    )
        self._outputs.append(
            _envelope(
                LOG_BLOCK,
                float(log.t_block[n - 1]),
                {
                    "run_id": log.run_id,
                    "start_index": log.flushed,
                    "n": n,
                    "t_sim_s": _b64(log.t_block[:n]),
                    "data": _b64(np.ascontiguousarray(block)),
                },
            )
        )
        log.flushed += n
        log.rows = 0

    def close_log(self, state: str = "completed") -> None:
        """Fecha o log aberto: último bloco e ``telemetry.log_end``."""
        log = self._log
        if log is None:
            return
        self._flush(log)
        self._end_pull(log, state)
        t_end = (log.start_tick + max(log.n_samples - 1, 0)) / self.sim_hz
        self._outputs.append(
            _envelope(
                LOG_END,
                t_end,
                {
                    "run_id": log.run_id,
                    "n_samples": log.n_samples,
                    "truncated": log.truncated,
                    "pulls": log.pulls,
                },
            )
        )
        self._log = None
        self._run_id = None
