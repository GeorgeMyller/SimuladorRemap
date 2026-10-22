"""Máquina de estados e programas das puxadas (dyno RF-06 a RF-09, RF-13 a RF-19).

Estados (seção 8): ``idle → arming → running → coastdown → completed``, com saídas
terminais ``aborted`` e ``engine_failed``; ``RunMachine`` recusa transições fora de
``RUN_STATE_TRANSITIONS`` e emite exatamente 1 ``run.state`` por transição. Mudanças de
fase sem mudança de estado (``multi_pull``: ``pull``, ``coastdown``, ``cooldown``) também
publicam ``run.state`` com ``previous_state == state``.

Programas (``RunController``), executados no worker em tempo simulado:

- ``baseline_pull``: arming segura ``start_rpm ± 25`` por 1,0 s com o PID e o pedal do
  pedido; ``running`` é inercial pura (``T_abs = 0``) até ``end_rpm``; ``coastdown`` com
  pedal 0 e frenagem PID até ``idle_rpm + 200``.
- ``sweep_pull``: igual, com ``running`` a seguir a rampa ``start_rpm + rate · t`` pelo PID;
  absorvedor em 0 por > 0,5 s com erro < −100 rpm ⇒ evento ``ramp_not_sustained``.
- ``steady_state_hold``: células na ordem enviada; PID de RPM + pedal fixo ou PID de MAP;
  estável com |Δrpm| < 25 e |ΔMAP| < 3 kPa por 0,5 s; ponto = média do último 1,0 s
  estável depois de ``hold_s``; ``cell_timeout_s`` ⇒ ``stable = false``.
- ``multi_pull``: N puxadas ``pull_type`` com arrefecimento em marcha lenta (ponto morto,
  ventilador se ``fan_on``) de ``cooldown_s`` simulados, acelerado ``COOLDOWN_SPEEDUP``×
  em tempo de parede (premissa OQ-01: o determinismo não muda).

Abortos (RF-14 a RF-17, EC-05, EC-07): ``FailureEvent`` catastrófico no tick ``k`` ⇒
``engine_failed`` com ``ended_at_tick = k + 1``; EGT pré-turbina acima de
``egt_limit_c + margem`` por ≥ 0,5 s (``egt_abort_enabled``); knock ``severe`` em ≥ 3 ciclos
seguidos de um cilindro com ``operator_protection``; ``arming`` > 10 s; ``running`` > 60 s
(puxadas); limitador de rotação ativo > 0,3 s ⇒ fim de ``running`` (``rev_limiter_hit``);
``coastdown`` > 15 s ⇒ ``completed`` com ``coastdown_timeout``.

Abort do usuário ou fecho de sessão em ``coastdown`` (que só pode terminar em
``completed``/``engine_failed``): a medição já acabou e a puxada fecha como ``completed``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Final, Literal

from simremap.damage.contracts import FailureEvent, KnockClass, KnockObservation
from simremap.dyno.contracts import (
    AbortReason,
    DynoCurvePoint,
    DynoRigConfig,
    DynoRun,
    DynoRunRequest,
    PullResult,
    RunState,
    RunStatePayload,
    RunSummary,
    RunType,
    SteadyStateCell,
    can_transition,
)
from simremap.dyno.correction import CorrectionResult
from simremap.dyno.curve import (
    BIN_RPM,
    CurveAggregator,
    CurveSample,
    MeanAccumulator,
    curve_sha256,
    peak_spread_pct,
    smooth_curve,
    summarize,
)
from simremap.dyno.rig import Driveline

__all__ = [
    "ARMING_STABLE_S",
    "ARMING_TIMEOUT_S",
    "COASTDOWN_TIMEOUT_S",
    "COOLDOWN_SPEEDUP",
    "EGT_ABORT_HOLD_S",
    "LIMITER_HOLD_S",
    "RUN_TIMEOUT_S",
    "SEVERE_KNOCK_CYCLES",
    "MeasuredSample",
    "RunContext",
    "RunController",
    "RunMachine",
    "TickObservation",
    "TickPlan",
    "forensic_report_url",
]

ARMING_TOLERANCE_RPM: Final = 25.0
ARMING_STABLE_S: Final = 1.0
ARMING_TIMEOUT_S: Final = 10.0
RUN_TIMEOUT_S: Final = 60.0
COASTDOWN_TIMEOUT_S: Final = 15.0
COASTDOWN_ABOVE_IDLE_RPM: Final = 200.0
LIMITER_HOLD_S: Final = 0.3
EGT_ABORT_HOLD_S: Final = 0.5
SEVERE_KNOCK_CYCLES: Final = 3
RAMP_ZERO_HOLD_S: Final = 0.5
RAMP_ERROR_RPM: Final = -100.0
CELL_RPM_TOL: Final = 25.0
CELL_MAP_TOL_KPA: Final = 3.0
CELL_SETTLE_S: Final = 0.5
CELL_AVERAGE_S: Final = 1.0
COOLDOWN_SPEEDUP: Final = 10
_ABSORBER_ZERO_NM: Final = 1.0

Phase = Literal["arming", "pull", "coastdown", "cooldown", "cells", "done"]


def forensic_report_url(run_id: str) -> str:
    return f"/api/v1/runs/{run_id}/forensic-report"


@dataclass(frozen=True, slots=True)
class RunContext:
    """Parâmetros fixos de uma puxada."""

    session_id: str
    run_id: str
    request: DynoRunRequest
    sim_hz: int
    driveline: Driveline
    rig: DynoRigConfig
    end_rpm: float
    idle_rpm: float
    egt_limit_c: float
    egt_abort_enabled: bool
    operator_protection: bool
    correction: CorrectionResult
    calibration_id: str
    calibration_hash: str
    seed: int
    started_at_tick: int
    egt_abort_margin_c: float = 0.0


@dataclass(slots=True)
class TickPlan:
    """O que a bancada faz no tick: marcha, pedal, absorvedor e ventilador."""

    gear: int
    pedal_pct: float
    absorber: Literal["free", "hold"]
    rpm_ref: float = 0.0
    ref_rate_rpm_s: float = 0.0
    fan_m_s: float = 0.0
    speedup: int = 1
    measure_tag: int | None = None
    map_target_kpa: float | None = None


@dataclass(slots=True)
class MeasuredSample:
    """Amostra medida (centro da janela de aceleração) e a fase em que foi produzida."""

    sample: CurveSample
    tag: int | None


@dataclass(slots=True)
class TickObservation:
    """Resultado do tick para a máquina de estados (depois de physics e damage)."""

    tick: int
    t_sim_s: float
    rpm: float
    egt_c: float
    map_kpa: float
    limiter_active: bool
    absorber_nm: float
    failures: list[FailureEvent] = field(default_factory=list)
    knock_last: list[KnockObservation | None] = field(default_factory=list)
    knock_events: int = 0
    measured: MeasuredSample | None = None


class RunMachine:
    """Estado da puxada com validação da tabela de transições (RF-13)."""

    __slots__ = ("state",)

    def __init__(self) -> None:
        self.state = RunState.IDLE

    def transition(self, target: RunState) -> RunState:
        if not can_transition(self.state, target):
            raise ValueError(f"transição inválida {self.state.value} → {target.value}")
        previous = self.state
        self.state = target
        return previous

    @property
    def terminal(self) -> bool:
        return self.state in (RunState.COMPLETED, RunState.ABORTED, RunState.ENGINE_FAILED)


@dataclass(slots=True)
class _PullData:
    index: int
    aggregator: CurveAggregator = field(default_factory=CurveAggregator)
    knock_events: int = 0
    events: set[str] = field(default_factory=set)


class RunController:
    """Programa de uma puxada (todos os ``RunType``) no tempo simulado do worker."""

    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        req = ctx.request
        self.request = req
        self.machine = RunMachine()
        self.dt = 1.0 / ctx.sim_hz
        self.multi = req.run_type == RunType.MULTI_PULL
        self.pull_kind = RunType(req.pull_type) if self.multi else req.run_type
        self.pull_count = req.pull_count if self.multi else 1
        self.pull_index = 1
        self.phase: Phase = "arming"
        self.phase_t0 = 0.0
        self.stable_s = 0.0
        self.t_running = 0.0
        self.limiter_s = 0.0
        self.egt_s = 0.0
        self.ramp_zero_s = 0.0
        self.severe_count: list[int] = []
        self.knock_seen: list[float] = []
        self.abort_reason: AbortReason | None = None
        self.ended_at_tick: int | None = None
        self.failure_event_id: str | None = None
        self._pending: tuple[RunState, AbortReason | None] | None = None
        self.outputs: list[RunStatePayload] = []
        self.pulls: list[PullResult] = []
        self.events: set[str] = set()
        self.knock_events = 0
        self._tag = 0
        self.current = _PullData(1)
        self.cell_index = 0
        self.cells: list[SteadyStateCell] = list(req.cells)
        self._cell_samples: deque[CurveSample] = deque(
            maxlen=max(1, round(CELL_AVERAGE_S * ctx.sim_hz))
        )
        self._cell_points: list[DynoCurvePoint] = []
        self._cell_pedals: list[float] = []
        self.last_rpm = 0.0
        self.last_t = 0.0
        self._result: DynoRun | None = None
        self.spin_up_pending = False

    # ------------------------------------------------------------------ propriedades
    @property
    def state(self) -> RunState:
        return self.machine.state

    @property
    def terminal(self) -> bool:
        return self.machine.terminal

    @property
    def start_rpm(self) -> float:
        if self.request.run_type == RunType.STEADY_STATE_HOLD:
            return self.cells[0].rpm
        return self.request.start_rpm

    def _progress(self) -> float:
        if self.terminal:
            return 100.0
        if self.request.run_type == RunType.STEADY_STATE_HOLD:
            return min(100.0, 100.0 * self.cell_index / max(len(self.cells), 1))
        span = max(self.ctx.end_rpm - self.request.start_rpm, 1.0)
        within = 0.0
        if self.phase == "pull":
            within = min(max((self.last_rpm - self.request.start_rpm) / span, 0.0), 1.0)
        elif self.phase in ("coastdown", "cooldown"):
            within = 1.0
        return min(100.0, 100.0 * ((self.pull_index - 1) + within) / self.pull_count)

    def _emit(self, previous: RunState | None) -> None:
        url = forensic_report_url(self.ctx.run_id) if self.state == RunState.ENGINE_FAILED else None
        self.outputs.append(
            RunStatePayload(
                session_id=self.ctx.session_id,
                run_id=self.ctx.run_id,
                run_type=self.request.run_type,
                state=self.state,
                previous_state=previous,
                phase=self.phase,
                pull_index=self.pull_index if self.multi else None,
                pull_count=self.pull_count if self.multi else None,
                abort_reason=self.abort_reason,
                progress_pct=self._progress(),
                rpm=max(self.last_rpm, 0.0),
                forensic_report_url=url,
            )
        )

    def _go(self, target: RunState, phase: Phase | None = None) -> None:
        previous = self.machine.transition(target)
        if phase is not None:
            self.phase = phase
        self._emit(previous)

    def _phase(self, phase: Phase, t: float) -> None:
        self.phase = phase
        self.phase_t0 = t
        self._emit(self.state)

    def drain(self) -> list[RunStatePayload]:
        out, self.outputs = self.outputs, []
        return out

    # ------------------------------------------------------------------ comandos
    def start(self, tick: int, t: float) -> None:
        """``idle → arming`` (aceitação de ``run.start``)."""
        self.phase_t0 = t
        self.last_t = t
        self.spin_up_pending = True
        self._go(RunState.ARMING, "arming")
        del tick

    def consume_spin_up(self) -> bool:
        """``True`` uma vez por arming: a bancada leva o conjunto à ``start_rpm``."""
        pending, self.spin_up_pending = self.spin_up_pending, False
        return pending

    def request_abort(self, reason: AbortReason) -> None:
        """Pedido de abort (usuário, sessão fechada, erro interno) aplicado no próximo tick."""
        if self.terminal or self._pending is not None:
            return
        self._pending = (RunState.ABORTED, reason)

    def begin_tick(self, tick: int) -> None:
        """Aplica falha/abort pendente na fronteira de tick (``ended_at_tick = tick``)."""
        if self._pending is None or self.terminal:
            return
        target, reason = self._pending
        self._pending = None
        if target == RunState.ABORTED and self.state == RunState.COASTDOWN:
            self.events.add(f"{reason.value}_in_coastdown" if reason else "abort_in_coastdown")
            self._finish(RunState.COMPLETED, None, tick)
            return
        self._finish(target, reason, tick)

    def fail_now(self, reason: AbortReason, tick: int) -> None:
        """Abort imediato (``internal_error``)."""
        if self.terminal:
            return
        if self.state == RunState.COASTDOWN:
            self.events.add("internal_error")
            self._finish(RunState.COMPLETED, None, tick)
            return
        self._finish(RunState.ABORTED, reason, tick)

    # ------------------------------------------------------------------ plano do tick
    def plan(self, t: float) -> TickPlan:  # noqa: PLR0911 - um ramo por fase
        req = self.request
        ctx = self.ctx
        fan = ctx.rig.fan_air_speed_m_s
        if self.phase == "arming":
            pedal = req.pedal_pct
            map_target = None
            if req.run_type == RunType.STEADY_STATE_HOLD:
                cell = self.cells[0]
                pedal = cell.pedal_pct if cell.pedal_pct is not None else req.pedal_pct
                map_target = cell.map_kpa
            return TickPlan(
                gear=req.gear,
                pedal_pct=pedal,
                absorber="hold",
                rpm_ref=self.start_rpm,
                fan_m_s=fan,
                map_target_kpa=map_target,
            )
        if self.phase == "pull":
            if self.pull_kind == RunType.BASELINE_PULL:
                return TickPlan(req.gear, req.pedal_pct, "free", fan_m_s=fan, measure_tag=self._tag)
            ref = min(req.start_rpm + req.ramp_rate_rpm_s * (t - self.t_running), ctx.end_rpm)
            rate = req.ramp_rate_rpm_s if ref < ctx.end_rpm else 0.0
            return TickPlan(
                req.gear,
                req.pedal_pct,
                "hold",
                rpm_ref=ref,
                ref_rate_rpm_s=rate,
                fan_m_s=fan,
                measure_tag=self._tag,
            )
        if self.phase == "cells":
            cell = self.cells[self.cell_index]
            return TickPlan(
                req.gear,
                cell.pedal_pct if cell.pedal_pct is not None else 0.0,
                "hold",
                rpm_ref=cell.rpm,
                fan_m_s=fan,
                measure_tag=self._tag,
                map_target_kpa=cell.map_kpa,
            )
        if self.phase == "coastdown":
            return TickPlan(req.gear, 0.0, "hold", rpm_ref=self._coast_target(), fan_m_s=fan)
        if self.phase == "cooldown":
            return TickPlan(
                0, 0.0, "free", fan_m_s=fan if req.fan_on else 0.0, speedup=COOLDOWN_SPEEDUP
            )
        return TickPlan(0, 0.0, "free", fan_m_s=fan)

    def _coast_target(self) -> float:
        return self.ctx.idle_rpm + COASTDOWN_ABOVE_IDLE_RPM

    # ------------------------------------------------------------------ observação
    def observe(self, obs: TickObservation) -> None:
        """Avança a máquina de estados com o resultado do tick ``obs.tick``."""
        if self.terminal:
            return
        self.last_rpm = obs.rpm
        self.last_t = obs.t_sim_s
        self.knock_events += obs.knock_events
        self.current.knock_events += obs.knock_events
        catastrophic = [f for f in obs.failures if f.catastrophic and not f.simulated_only]
        if catastrophic:
            if self.failure_event_id is None:
                self.failure_event_id = catastrophic[0].failure_event_id
            self._pending = (RunState.ENGINE_FAILED, AbortReason.CATASTROPHIC_FAILURE)
            return
        if self.phase in ("arming", "pull", "cells") and self._protection_abort(obs):
            return
        t = obs.t_sim_s
        elapsed = t - self.phase_t0
        if self.phase == "arming":
            self._arming(obs, elapsed)
        elif self.phase == "pull":
            self._pull(obs, t)
        elif self.phase == "cells":
            self._cells(obs, t)
        elif self.phase == "coastdown":
            self._coastdown(obs, elapsed)
        elif self.phase == "cooldown" and elapsed >= self.request.cooldown_s - 1e-9:
            self._next_pull(obs, t)

    def _protection_abort(self, obs: TickObservation) -> bool:
        ctx = self.ctx
        hold = round(EGT_ABORT_HOLD_S * ctx.sim_hz)
        if ctx.egt_abort_enabled and obs.egt_c > ctx.egt_limit_c + ctx.egt_abort_margin_c:
            self.egt_s += 1
            if self.egt_s >= hold:
                self._finish(RunState.ABORTED, AbortReason.EGT_LIMIT, obs.tick)
                return True
        else:
            self.egt_s = 0
        if ctx.operator_protection and obs.knock_last:
            n = len(obs.knock_last)
            if len(self.severe_count) != n:
                self.severe_count = [0] * n
                self.knock_seen = [-1.0] * n
            for i, ko in enumerate(obs.knock_last):
                if ko is None or ko.t_sim_s <= self.knock_seen[i]:
                    continue
                self.knock_seen[i] = ko.t_sim_s
                if ko.knock_class == KnockClass.SEVERE:
                    self.severe_count[i] += 1
                else:
                    self.severe_count[i] = 0
                if self.severe_count[i] >= SEVERE_KNOCK_CYCLES:
                    self._finish(RunState.ABORTED, AbortReason.SEVERE_KNOCK_PROTECTION, obs.tick)
                    return True
        return False

    def _arming(self, obs: TickObservation, elapsed: float) -> None:
        if abs(obs.rpm - self.start_rpm) < ARMING_TOLERANCE_RPM:
            self.stable_s += self.dt
        else:
            self.stable_s = 0.0
        if self.stable_s >= ARMING_STABLE_S - 1e-9:
            self._begin_measure(obs.t_sim_s)
            return
        if elapsed >= ARMING_TIMEOUT_S - 1e-9:
            self._finish(RunState.ABORTED, AbortReason.ARMING_TIMEOUT, obs.tick)

    def _begin_measure(self, t: float) -> None:
        self._tag += 1
        self.t_running = t
        self.phase_t0 = t
        self.limiter_s = 0.0
        self.ramp_zero_s = 0.0
        if self.request.run_type == RunType.STEADY_STATE_HOLD:
            self.cell_index = 0
            self._start_cell(t)
            self._go(RunState.RUNNING, "cells")
        elif self.state == RunState.ARMING:
            self._go(RunState.RUNNING, "pull")
        else:
            self._phase("pull", t)

    def _accept(self, obs: TickObservation, low: float, high: float) -> CurveSample | None:
        m = obs.measured
        if m is None or m.tag != self._tag:
            return None
        half = BIN_RPM / 2.0
        if not low - half <= m.sample.rpm < high - half:  # só intervalos completos
            return None
        return m.sample

    def _pull(self, obs: TickObservation, t: float) -> None:
        req = self.request
        ctx = self.ctx
        sample = self._accept(obs, req.start_rpm, ctx.end_rpm)
        if sample is not None:
            self.current.aggregator.add(sample)
        if self.pull_kind == RunType.SWEEP_PULL:
            ref = req.start_rpm + req.ramp_rate_rpm_s * (t - self.t_running)
            if obs.absorber_nm <= _ABSORBER_ZERO_NM and obs.rpm - ref < RAMP_ERROR_RPM:
                self.ramp_zero_s += self.dt
                if self.ramp_zero_s > RAMP_ZERO_HOLD_S:
                    self.current.events.add("ramp_not_sustained")
            else:
                self.ramp_zero_s = 0.0
        self.limiter_s = self.limiter_s + self.dt if obs.limiter_active else 0.0
        if obs.rpm >= ctx.end_rpm:
            self._end_pull(t)
        elif self.limiter_s > LIMITER_HOLD_S:
            self.current.events.add("rev_limiter_hit")
            self._end_pull(t)
        elif t - self.t_running >= RUN_TIMEOUT_S - 1e-9:
            self._finish(RunState.ABORTED, AbortReason.RUN_TIMEOUT, obs.tick)

    def _end_pull(self, t: float) -> None:
        self._tag += 1  # amostras atrasadas da janela deixam de contar
        if self.pull_index == self.pull_count:
            self.phase_t0 = t
            self._go(RunState.COASTDOWN, "coastdown")
        else:
            self._phase("coastdown", t)

    def _coastdown(self, obs: TickObservation, elapsed: float) -> None:
        done = obs.rpm <= self._coast_target()
        timeout = elapsed >= COASTDOWN_TIMEOUT_S - 1e-9
        if not (done or timeout):
            return
        if timeout and not done:
            self.current.events.add("coastdown_timeout")
        self._close_pull(RunState.COMPLETED)
        if self.pull_index < self.pull_count:
            self._phase("cooldown", obs.t_sim_s)
            return
        self._finish(RunState.COMPLETED, None, obs.tick)

    def _next_pull(self, obs: TickObservation, t: float) -> None:
        self.pull_index += 1
        self.current = _PullData(self.pull_index)
        self.stable_s = 0.0
        self.spin_up_pending = True
        self._phase("arming", t)
        del obs

    # ------------------------------------------------------------------ células
    def _start_cell(self, t: float) -> None:
        self.phase_t0 = t
        self.stable_s = 0.0
        self._cell_samples.clear()

    def _cells(self, obs: TickObservation, t: float) -> None:
        cell = self.cells[self.cell_index]
        ok = abs(obs.rpm - cell.rpm) < CELL_RPM_TOL
        if cell.map_kpa is not None:
            ok = ok and abs(obs.map_kpa - cell.map_kpa) < CELL_MAP_TOL_KPA
        self.stable_s = self.stable_s + self.dt if ok else 0.0
        m = obs.measured
        if m is not None and m.tag == self._tag:
            self._cell_samples.append(m.sample)  # último 1,0 s, estável ou não
        elapsed = t - self.phase_t0
        settled = self.stable_s >= CELL_SETTLE_S + CELL_AVERAGE_S - 1e-9
        full = len(self._cell_samples) >= (self._cell_samples.maxlen or 1)
        if settled and full and elapsed >= cell.hold_s - 1e-9:
            self._record_cell(stable=True)
        elif elapsed >= self.request.cell_timeout_s - 1e-9:
            self.current.events.add("cell_not_stable")
            self._record_cell(stable=False)
        else:
            return
        self.cell_index += 1
        if self.cell_index >= len(self.cells):
            self._end_pull(t)
            return
        self._tag += 1
        self._start_cell(t)
        self._phase("cells", t)

    def _record_cell(self, *, stable: bool) -> None:
        acc = MeanAccumulator()
        for s in self._cell_samples:
            acc.add(s)
        if acc.count == 0:
            self._cell_points.append(self._empty_cell_point())
            self._cell_pedals.append(0.0)
            return
        self._cell_points.append(
            acc.point(self.ctx.correction.factor, cell_index=self.cell_index, stable=stable)
        )
        self._cell_pedals.append(acc.mean("pedal_pct"))

    def _empty_cell_point(self) -> DynoCurvePoint:
        cell = self.cells[self.cell_index]
        return DynoCurvePoint.model_validate(
            {
                "rpm": cell.rpm,
                "t_sim_s": max(self.last_t, 0.0),
                "power_wheel_kw": 0.0,
                "power_wheel_kw_corr": 0.0,
                "power_crank_kw": 0.0,
                "power_crank_kw_corr": 0.0,
                "torque_wheel_nm": 0.0,
                "torque_engine_nm": 0.0,
                "torque_engine_nm_corr": 0.0,
                "lambda": 0.0,
                "afr": 0.0,
                "egt_c": 0.0,
                "map_kpa": 0.0,
                "iat_c": 0.0,
                "ect_c": 0.0,
                "oil_c": 0.0,
                "ignition_deg_btdc": 0.0,
                "knock_retard_max_deg": 0.0,
                "cell_index": self.cell_index,
                "stable": False,
            }
        )

    # ------------------------------------------------------------------ resultado
    def _pull_curve(self) -> tuple[list[DynoCurvePoint], list[float]]:
        if self.request.run_type == RunType.STEADY_STATE_HOLD:
            return list(self._cell_points), list(self._cell_pedals)
        agg = self.current.aggregator
        return agg.points(self.ctx.correction.factor), agg.pedals()

    def _summary(
        self, curve: list[DynoCurvePoint], pedals: list[float], data: _PullData, final: bool
    ) -> RunSummary:
        window = (
            1
            if self.request.run_type == RunType.STEADY_STATE_HOLD
            else self.request.smoothing_window
        )
        failed = final and self.state == RunState.ENGINE_FAILED
        return summarize(
            curve,
            smooth_curve(curve, window),
            pedals,
            self.ctx.correction,
            knock_events=data.knock_events if not final else self.knock_events,
            event_codes=(data.events | self.events) if final else data.events,
            failure_event_id=self.failure_event_id if final else None,
            forensic_report_url=forensic_report_url(self.ctx.run_id) if failed else None,
        )

    def _close_pull(self, state: RunState) -> None:
        if not self.multi:
            return
        curve, pedals = self._pull_curve()
        self.events |= self.current.events
        self.pulls.append(
            PullResult(
                pull_index=self.pull_index,
                state=state,
                summary=self._summary(curve, pedals, self.current, final=False),
                curve=curve,
            )
        )

    def _finish(self, target: RunState, reason: AbortReason | None, tick: int) -> None:
        self.abort_reason = reason
        self.ended_at_tick = tick
        self.phase = "done"
        self._go(target)
        self._result = self._build_result()

    def _build_result(self) -> DynoRun:
        ctx = self.ctx
        if self.multi:
            last = self.pulls[-1] if self.pulls else None
            curve = list(last.curve) if last is not None else []
            pedals = [self.request.pedal_pct] * len(curve)
            self.events |= self.current.events
            completed = [p for p in self.pulls if p.state == RunState.COMPLETED]
            whp = [p.summary.peak_whp for p in completed]
            torque = [p.summary.peak_torque_engine_nm for p in completed]
            repeatability: dict[str, float] | None = {
                "peak_whp_spread_pct": peak_spread_pct(whp),
                "peak_torque_spread_pct": peak_spread_pct(torque),
            }
            sha = curve_sha256([p.curve for p in self.pulls])
        else:
            curve, pedals = self._pull_curve()
            repeatability = None
            sha = curve_sha256(curve)
        data = self.current
        data.events |= self.events
        summary = self._summary(curve, pedals, data, final=True)
        return DynoRun(
            run_id=ctx.run_id,
            session_id=ctx.session_id,
            run_type=self.request.run_type,
            request=self.request,
            state=self.state,
            abort_reason=self.abort_reason,
            started_at_tick=ctx.started_at_tick,
            ended_at_tick=self.ended_at_tick,
            calibration_id=ctx.calibration_id,
            calibration_hash=ctx.calibration_hash,
            seed=ctx.seed,
            sim_hz=ctx.sim_hz,
            summary=summary,
            curve=curve,
            pulls=list(self.pulls),
            repeatability=repeatability,
            curve_sha256=sha,
        )

    def result(self) -> DynoRun:
        if self._result is None:
            raise RuntimeError("puxada ainda não terminou")
        return self._result

    def add_event(self, code: str) -> None:
        """Evento do laço (``realtime_degraded``, ``telemetry_degraded``...)."""
        self.events.add(code)
