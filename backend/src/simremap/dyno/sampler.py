"""Saída do laço para a telemetria: ``TickRecord`` e amostrador de frames (simulation-bus 3.5).

O ``DynoSimTask`` entrega um ``TickRecord`` por tick a um ``TickSampler`` (passo 5 da
ordem do tick). O dono do formato final é o ``telemetry-datalogger`` (D-BUS-06): ele pode
fornecer a sua classe pelo campo ``sampler`` do ``init_payload`` (``"modulo:Classe"``,
construída com ``(session_id, sim_hz, fps, n_cyl, afr_stoich)``). Enquanto não existe, vale
``FrameSampler``: frames ``telemetry.frame`` na fronteira ``floor(k · fps / sim_hz)`` com os
canais escalares do catálogo (agregação ``last``/``max``/``min``/``any`` da seção 5 do
contrato WS), sem espectro nem traço de pressão.

O ``seq`` dos envelopes é atribuído no event loop (``dyno.stream``), nunca no worker.
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

import orjson

from simremap.damage.contracts import DamageState
from simremap.dyno.contracts import DynoLoad
from simremap.ecu.contracts import EcuStepResult
from simremap.physics.contracts import ActuatorCommands, EngineState, SensorReadings

__all__ = [
    "DEFAULT_FPS",
    "FrameSampler",
    "TickRecord",
    "TickSampler",
    "load_sampler",
]

DEFAULT_FPS: Final = 50

_LAST: Final = (
    "rpm",
    "map_kpa",
    "baro_kpa",
    "boost_bar",
    "lambda",
    "lambda_measured",
    "afr",
    "iat_c",
    "ect_c",
    "oil_temp_c",
    "turbo_rpm",
    "wastegate_duty_pct",
    "torque_nm",
    "power_kw",
    "whp",
    "throttle_pct",
    "pedal_pct",
    "load_pct",
    "lambda_target",
    "boost_target_kpa",
    "roller_speed_kmh",
    "absorber_nm",
    "real_time_factor",
    "cam_intake_deg",
    "cam_exhaust_deg",
    "cam_intake_target_deg",
    "cam_exhaust_target_deg",
    "ethanol_pct",
)
_MAX: Final = (
    "knock_retard_deg",
    "egt_c",
    "egt_pre_turbo_c",
    "injector_duty_pct",
    "cyl_pressure_peak_bar",
)
_MIN: Final = ("health_min_pct",)
_ANY: Final = ("fuel_cut", "ign_cut")


@dataclass(slots=True)
class TickRecord:
    """Tudo o que o tick produziu (sem cópias; não guardar além do ``on_tick``)."""

    tick: int
    t_sim_s: float
    sensors: SensorReadings
    commands: ActuatorCommands
    ecu: EcuStepResult
    state: EngineState
    damage: DamageState
    load: DynoLoad
    run_id: str | None
    absorber_nm: float = 0.0
    roller_speed_kmh: float = 0.0
    real_time_factor: float | None = None


@runtime_checkable
class TickSampler(Protocol):
    def on_tick(self, rec: TickRecord) -> None: ...
    def set_fps(self, fps: int) -> None: ...
    def drain(self) -> list[bytes]: ...


def _mean_lambda(state: EngineState) -> float | None:
    values = [v for v in state.lambda_cyl if v is not None and math.isfinite(v)]
    return math.fsum(values) / len(values) if values else None


def _finite(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return value


class FrameSampler:
    """Amostrador padrão de ``telemetry.frame`` (canais escalares)."""

    def __init__(
        self, session_id: str, sim_hz: int, fps: int, n_cyl: int, afr_stoich: float
    ) -> None:
        self.session_id = session_id
        self.sim_hz = sim_hz
        self.fps = fps
        self.n_cyl = n_cyl
        self.afr_stoich = afr_stoich
        self._pending_fps: int | None = None
        self._frame_index: int | None = None
        self._window_ticks = 0
        self._last_rec: TickRecord | None = None
        self._max: dict[str, float | None] = {}
        self._min: dict[str, float | None] = {}
        self._any: dict[str, bool] = {}
        self._run_id: str | None = None
        self._outputs: list[bytes] = []
        self._t_close = 0.0
        self._tick_close = 0

    def set_fps(self, fps: int) -> None:
        """Nova taxa a partir da próxima fronteira de frame (30..60)."""
        self._pending_fps = min(max(int(fps), 30), 60)

    def _index(self, tick: int) -> int:
        return (tick * self.fps) // self.sim_hz

    def _last_values(self, rec: TickRecord) -> dict[str, float | None]:
        """Canais ``last`` (calculados só no fecho do frame, a partir do último tick)."""
        s, st, ecu = rec.sensors, rec.state, rec.ecu
        lam = _mean_lambda(st)
        return {
            "rpm": st.rpm,
            "map_kpa": s.map_kpa,
            "baro_kpa": s.baro_kpa,
            "boost_bar": (s.map_kpa - s.baro_kpa) / 100.0,
            "lambda": lam,
            "lambda_measured": s.lambda_measured,
            "afr": None if lam is None else lam * self.afr_stoich,
            "iat_c": s.iat_c,
            "ect_c": s.ect_c,
            "oil_temp_c": s.oil_temp_c,
            "turbo_rpm": s.turbo_rpm,
            "wastegate_duty_pct": rec.commands.wastegate_duty_pct
            if s.turbo_rpm is not None
            else None,
            "torque_nm": st.torque_nm,
            "power_kw": st.power_kw,
            "whp": st.whp,
            "throttle_pct": s.tps_pct,
            "pedal_pct": rec.load.pedal_pct,
            "load_pct": ecu.status.load_pct,
            "lambda_target": ecu.status.lambda_target,
            "boost_target_kpa": ecu.status.boost_target_kpa,
            "roller_speed_kmh": rec.roller_speed_kmh,
            "absorber_nm": rec.absorber_nm,
            "real_time_factor": rec.real_time_factor,
            "cam_intake_deg": s.cam_intake_deg,
            "cam_exhaust_deg": s.cam_exhaust_deg,
            "cam_intake_target_deg": rec.commands.vvt_intake_target_deg,
            "cam_exhaust_target_deg": rec.commands.vvt_exhaust_target_deg,
            "ethanol_pct": s.ethanol_pct,
        }

    def _update_extremes(self, rec: TickRecord) -> None:
        s, st, ecu = rec.sensors, rec.state, rec.ecu
        healths = [c.health for c in rec.damage.components]
        mx: dict[str, float | None] = {
            "knock_retard_deg": max(ecu.status.knock_retard_deg, default=0.0),
            "egt_c": max(s.egt_c, default=0.0),
            "egt_pre_turbo_c": s.egt_collector_c,
            "injector_duty_pct": ecu.status.inj_duty_pct,
            "cyl_pressure_peak_bar": max(st.p_max_kpa, default=0.0) / 100.0,
        }
        mn: dict[str, float | None] = {
            "health_min_pct": 100.0 * min(healths) if healths else None,
        }
        an = {"fuel_cut": any(rec.commands.fuel_cut), "ign_cut": any(rec.commands.spark_cut)}
        for key, value in mx.items():
            v = _finite(value)
            prev = self._max.get(key)
            self._max[key] = v if prev is None else (prev if v is None else max(prev, v))
        for key, value in mn.items():
            v = _finite(value)
            prev = self._min.get(key)
            self._min[key] = v if prev is None else (prev if v is None else min(prev, v))
        for key, flag in an.items():
            self._any[key] = self._any.get(key, False) or flag

    def on_tick(self, rec: TickRecord) -> None:
        index = self._index(rec.tick)
        if self._frame_index is not None and index != self._frame_index:
            self._close()
            if self._pending_fps is not None:
                self.fps = self._pending_fps
                self._pending_fps = None
                index = self._index(rec.tick)
        self._frame_index = index
        self._update_extremes(rec)
        self._last_rec = rec
        self._window_ticks += 1
        self._run_id = rec.run_id
        self._t_close = rec.t_sim_s
        self._tick_close = rec.tick

    def _close(self) -> None:
        if self._frame_index is None or self._window_ticks == 0 or self._last_rec is None:
            return
        last = self._last_values(self._last_rec)
        channels: dict[str, Any] = {k: _finite(v) for k, v in last.items()}
        channels.update(self._max)
        channels.update(self._min)
        channels.update({k: 1.0 if v else 0.0 for k, v in self._any.items()})
        payload = {
            "session_id": self.session_id,
            "run_id": self._run_id,
            "frame_index": self._frame_index,
            "window_ticks": self._window_ticks,
            "channels": channels,
            "knock_spectrum": None,
            "cyl_pressure_trace": None,
            "stats": {
                "fps_actual": float(self.fps),
                "dropped_frames": 0,
                "dropped_events": 0,
                "real_time_factor": channels.get("real_time_factor"),
                "tick": self._tick_close,
            },
        }
        self._outputs.append(
            orjson.dumps(
                {"v": 1, "type": "telemetry.frame", "t_sim_s": self._t_close, "payload": payload}
            )
        )
        self._window_ticks = 0
        self._max = {}
        self._min = {}
        self._any = {}

    def drain(self) -> list[bytes]:
        out, self._outputs = self._outputs, []
        return out


def load_sampler(
    spec: str | None, *, session_id: str, sim_hz: int, fps: int, n_cyl: int, afr_stoich: float
) -> TickSampler:
    """Instancia ``spec`` (``"modulo:Classe"``) ou o ``FrameSampler`` padrão."""
    if not spec:
        return FrameSampler(session_id, sim_hz, fps, n_cyl, afr_stoich)
    module_name, _, attr = spec.partition(":")
    cls = getattr(importlib.import_module(module_name), attr)
    sampler = cls(session_id, sim_hz, fps, n_cyl, afr_stoich)
    if not isinstance(sampler, TickSampler):
        raise TypeError(f"{spec!r} não implementa TickSampler")
    return sampler
