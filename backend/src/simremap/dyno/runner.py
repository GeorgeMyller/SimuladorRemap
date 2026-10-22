"""``DynoSimTask``: o ``SimTask`` do laço da sessão (dyno RF-03, RF-26; simulation-bus 1, 3.6).

Executado só no worker (``SimWorkerHost``, ``"simremap.dyno.runner:DynoSimTask"``). Ordem
de cada tick ``k`` (``dt = 1 / sim_hz``)::

    (fronteira) comandos pendentes: calibration.apply, falha/abort da puxada
    1. sensors   = physics.read_sensors(damage.knock_signal())
    2. ecu       = ecu.step(sensors, dt)            + sonda (ignition_offset_deg) depois
    (dyno)       controladores e DynoLoad              da arbitragem
    3. state     = physics.step(commands, load, dt)
    4. damage    = damage.step(state, dt, ecu.status)  (pode chamar physics.lock)
    5. telemetry = sampler.on_tick(TickRecord(...)) + medição do rolo + máquina de estados

Comandos (``handle_command``; tabela da seção 3.6):

- ``run.start`` ``{run_id, request}`` → puxada em ``arming`` (``run.state``);
- ``run.abort`` ``{run_id, reason}`` → ``aborted`` no tick seguinte;
- ``calibration.apply`` ``{request_id, ...}`` → troca na fronteira do próximo tick e ``ack``
  com ``applied_t_sim_s`` depois desse ``ecu.step``; ``calibration.cancel`` descarta o pedido
  ainda não aplicado;
- ``hardware.install`` ``{request_id, vehicle, exhaust_backpressure_scale,
  fuel_pump_capacity_scale}`` → peças da oficina com a sessão viva (sem puxada): física e
  dano novos (``assembly.install_hardware``), partida em ponto morto e ``ack`` com a saúde;
- ``engine.restore`` → ``DamageModel.restore`` + ``PhysicsEngine.reset_mechanical`` e
  ``ack`` com a saúde;
- ``engine.health`` → ``ack`` com ``EngineHealth`` e pesos das bielas;
- ``operator.throttle`` ``{throttle_pct}`` → pedal só sem puxada, senão ``error``
  ``THROTTLE_LOCKED_BY_RUN``;
- ``telemetry.config`` ``{fps?, spectrum?, pressure_trace?, real_time_factor?}`` →
  ``sampler.set_fps`` e, se o amostrador tiver ``configure``, ``sampler.configure(spectrum,
  pressure_trace)`` (espectro/traço só com ≥ 1 conexão a pedi-los); ``real_time_factor``
  (medido no event loop a 1 Hz) vai para ``TickRecord.real_time_factor``.

O gerador do espectro do dano (``DamageModel.spectrum_frame``) é ligado ao amostrador
com ``bind_spectrum`` no setup e sempre que o dano da sessão troca (sondas, RF-26).

Saídas (``drain_outputs``, envelopes ``{"v", "type", "t_sim_s", "payload"}`` sem ``seq``):
``telemetry.frame``, ``event.knock`` (faixa de dados), ``run.state``, ``event.failure``,
``event.limiter``, ``error``, ``ack``, ``damage.trace`` e ``run.result`` (faixa crítica).

Exceção no tick (EC-14): a puxada passa a ``aborted`` (``internal_error``), sai um
``error`` ``SIM_INTERNAL_ERROR`` e a sessão volta a ``idle``; o laço continua.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any, Final

import orjson

from simremap.catalog.contracts import VehicleSpec
from simremap.core.worker.logbridge import worker_log
from simremap.damage.model import DamageModel
from simremap.dyno.assembly import (
    DynoInitPayload,
    SessionParts,
    assemble,
    install_hardware,
    swap_ecu_stage,
)
from simremap.dyno.contracts import AbortReason, DynoRunRequest, ProbeOverrides, RunState, RunType
from simremap.dyno.controllers import LoadController, RpmController
from simremap.dyno.curve import CurveSample
from simremap.dyno.errors import WS_ONLY_CODES
from simremap.dyno.rig import AccelerationWindow, measure_roll
from simremap.dyno.runs import (
    COASTDOWN_ABOVE_IDLE_RPM,
    MeasuredSample,
    RunContext,
    RunController,
    TickObservation,
    TickPlan,
)
from simremap.dyno.sampler import TickRecord
from simremap.dyno.trace_codec import encode_trace
from simremap.ecu.contracts import EcuStepResult
from simremap.physics.contracts import ActuatorCommands, EngineState, SensorReadings

__all__ = ["IGNITION_MAX_DEG", "IGNITION_MIN_DEG", "DynoSimTask", "apply_probe"]

IGNITION_MIN_DEG: Final = -30.0
IGNITION_MAX_DEG: Final = 60.0
_MAX_ERRORS_PER_RUN: Final = 5
PEDAL_RATE_PCT_S: Final = 100.0
INSTALL_WARMUP_S: Final = 1.0  # marcha lenta depois de instalar peças (física + ECU)
ARMING_PEDAL_CAP_RATE_PCT_S: Final = 40.0  # %/s do limitador de pedal no arming
ARMING_SATURATION_RATIO: Final = 0.97  # absorvedor ≥ 97 % da capacidade ⇒ saturado
ARMING_RELEASE_RATIO: Final = 0.85  # absorvedor < 85 % da capacidade ⇒ o teto volta a subir
ARMING_PEDAL_CAP_RELEASE_PCT_S: Final = 10.0  # %/s de subida do teto (entre 85 e 97 %: fixo)
"""Taxa máxima do pedal do operador da bancada (%/s): evita *tip-in* instantâneo."""


def apply_probe(commands: ActuatorCommands, probe: ProbeOverrides) -> ActuatorCommands:
    """Soma ``ignition_offset_deg`` ao avanço depois da arbitragem da ECU (RF-26)."""
    if probe.ignition_offset_deg == 0.0:
        return commands
    shifted = [
        min(max(a + probe.ignition_offset_deg, IGNITION_MIN_DEG), IGNITION_MAX_DEG)
        for a in commands.ignition_advance_deg
    ]
    return commands.model_copy(update={"ignition_advance_deg": shifted})


def _number(command: dict[str, object], key: str, default: float = 1.0) -> float:
    value = command.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} deve ser numérico")
    return float(value)


@dataclass(slots=True)
class _Centre:
    """Item da janela de aceleração (amostra alinhada com ``α_roll``)."""

    tag: int
    gear: int
    rpm: float
    t_sim_s: float
    absorber_nm: float
    loss_nm: float
    lambda_: float
    egt_c: float
    map_kpa: float
    iat_c: float
    ect_c: float
    oil_c: float
    ignition_deg: float
    knock_retard: float
    pedal_pct: float


def _envelope(kind: str, t_sim_s: float, payload: Any) -> bytes:
    return orjson.dumps({"v": 1, "type": kind, "t_sim_s": t_sim_s, "payload": payload})


class DynoSimTask:
    """Laço de simulação de uma sessão (``SimTask``)."""

    def __init__(self) -> None:
        self.parts: SessionParts | None = None
        self.tick_index = 0
        self.sim_hz = 1000
        self.dt = 1.0 / self.sim_hz
        self.steps_per_tick = 1
        self.wall_budget_ticks = 1  # orçamento de parede do último tick (worker.overrun)
        self.run: RunController | None = None
        self.probe: ProbeOverrides | None = None
        self.operator_pedal = 0.0
        self.pedal = 0.0
        self.arming_pedal_cap = 100.0
        self.paused = False
        self.post_coast = False
        self.last_state: EngineState | None = None
        self.last_ecu: EcuStepResult | None = None
        self.limiter_state = "off"
        self.window: AccelerationWindow[_Centre] | None = None
        self._outputs: list[bytes] = []
        self._apply_queue: list[dict[str, object]] = []
        self._apply_acks: list[dict[str, object]] = []
        self._main_damage: DamageModel | None = None
        self._errors_in_run = 0
        self._rpm_ctl: RpmController | None = None
        self._load_ctl: LoadController | None = None
        self._last_mode = ""
        self._warnings_in_run = 0
        self.calibration_id = ""
        self.calibration_hash = ""
        self.real_time_factor: float | None = None

    # ------------------------------------------------------------------ propriedades
    @property
    def session(self) -> SessionParts:
        if self.parts is None:
            raise RuntimeError("DynoSimTask sem setup")
        return self.parts

    @property
    def t_sim_s(self) -> float:
        return self.tick_index / self.sim_hz

    @property
    def run_active(self) -> bool:
        return self.run is not None and not self.run.terminal

    def _emit(self, kind: str, payload: Any, t_sim_s: float | None = None) -> None:
        self._outputs.append(_envelope(kind, self.t_sim_s if t_sim_s is None else t_sim_s, payload))

    def _ws_error(self, code: str, detail: str = "", *, fatal: bool = False) -> None:
        self._emit(
            "error",
            {
                "code": code,
                "title": WS_ONLY_CODES.get(code, code),
                "detail": detail,
                "fatal": fatal,
            },
        )

    def _ack(self, command: str, request_id: object, ok: bool = True, **extra: Any) -> None:
        self._emit("ack", {"command": command, "request_id": request_id, "ok": ok, **extra})

    # ------------------------------------------------------------------ SimTask
    def setup(self, init_payload: bytes) -> None:
        payload = DynoInitPayload.model_validate_json(init_payload)
        self.setup_payload(payload)

    def setup_payload(self, payload: DynoInitPayload) -> None:
        """Monta a sessão a partir do payload já validado (testes sem worker)."""
        parts = assemble(payload)
        self.parts = parts
        self.sim_hz = payload.sim_hz
        self.dt = 1.0 / payload.sim_hz
        self.steps_per_tick = payload.steps_per_tick
        self._main_damage = parts.damage
        self.calibration_id = payload.calibration_id
        self.calibration_hash = payload.calibration_hash
        self.window = AccelerationWindow(payload.rig.accel_window_ticks, self.dt)
        self._rpm_ctl = RpmController(
            payload.rig.rpm_pid, parts.driveline, payload.rig.roller_inertia_kg_m2
        )
        self._load_ctl = LoadController(payload.rig.load_pid)
        self._bind_spectrum()
        if payload.spectrum is not None or payload.pressure_trace is not None:
            self._configure_sampler(payload.spectrum, payload.pressure_trace)
        parts.physics.crank(payload.idle_rpm)
        self._warmup(payload.warmup_s)
        self.paused = payload.hold_until_command
        self._emit(
            "session.ready",
            {
                "session_id": payload.session_id,
                "seed": payload.seed,
                "sim_hz": payload.sim_hz,
                "calibration_hash": payload.calibration_hash,
                "rod_weights": parts.damage.rod_weights,
                "profile_id": parts.ecu.profile_id,
                "ecu_state": parts.ecu.ecu_state,
                "spectrum_available": callable(getattr(parts.sampler, "bind_spectrum", None)),
            },
        )

    def _bind_spectrum(self) -> None:
        """Liga ``damage.spectrum_frame`` ao amostrador (se ele aceitar ``bind_spectrum``)."""
        parts = self.session
        bind = getattr(parts.sampler, "bind_spectrum", None)
        if callable(bind):
            bind(parts.damage.spectrum_frame)

    def _configure_sampler(self, spectrum: object, pressure_trace: object) -> None:
        configure = getattr(self.session.sampler, "configure", None)
        if not callable(configure):
            return
        configure(
            spectrum=spectrum if isinstance(spectrum, bool) else None,
            pressure_trace=pressure_trace if isinstance(pressure_trace, bool) else None,
        )

    def _cmd_telemetry_config(self, command: dict[str, object]) -> None:
        fps = command.get("fps")
        if isinstance(fps, int | float) and not isinstance(fps, bool):
            self.session.sampler.set_fps(int(fps))
        spectrum = command.get("spectrum")
        trace = command.get("pressure_trace")
        if isinstance(spectrum, bool) or isinstance(trace, bool):
            self._configure_sampler(spectrum, trace)
        rtf = command.get("real_time_factor")
        if isinstance(rtf, int | float) and not isinstance(rtf, bool) and rtf >= 0.0:
            self.real_time_factor = float(rtf)

    def _warmup(self, seconds: float) -> None:
        """Partida e estabilização da marcha lenta antes do tick 0 da sessão.

        A partida a ``idle_rpm`` com o coletor à pressão ambiente gera uma rajada de
        rotação e um corte de combustível em desaceleração; o transitório faz parte da
        inicialização (spec 6.2, passo 2), por isso corre só física + ECU em ponto
        morto, sem dano, sem telemetria e sem saídas. O tempo simulado da sessão
        continua a partir do fim do aquecimento.
        """
        parts = self.session
        physics, rig = parts.physics, parts.rig
        for _ in range(round(seconds * self.sim_hz)):
            sensors = physics.read_sensors()
            ecu = parts.ecu.step(sensors, self.dt)
            load = rig.load(
                rpm=physics.rpm,
                brake_torque_nm=0.0,
                absorber_command_nm=0.0,
                dt=self.dt,
                pedal_pct=0.0,
                fan_air_speed_m_s=parts.payload.rig.fan_air_speed_m_s,
            )
            self.last_state = physics.step(ecu.commands, load, self.dt)
        self.tick_index = round(physics.t_sim_s * self.sim_hz)

    def drain_outputs(self) -> list[bytes]:
        if self.parts is not None:
            self._outputs.extend(self.parts.sampler.drain())
        out, self._outputs = self._outputs, []
        return out

    def teardown(self) -> None:
        if self.run_active and self.run is not None:
            self.run.fail_now(AbortReason.SESSION_CLOSED, self.tick_index)
            self._finalize_run()

    # ------------------------------------------------------------------ comandos
    def handle_command(self, command: dict[str, object]) -> None:
        kind = command.get("type")
        request_id = command.get("request_id")
        try:
            if kind == "run.start":
                self._cmd_run_start(command)
            elif kind == "run.abort":
                self._cmd_run_abort(command)
            elif kind in ("calibration.apply", "ecu.swap"):
                self._apply_queue.append(command)
            elif kind in ("calibration.cancel", "ecu.swap.cancel"):
                before = len(self._apply_queue)
                self._apply_queue = [
                    c for c in self._apply_queue if c.get("request_id") != request_id
                ]
                self._ack(str(kind), request_id, cancelled=before != len(self._apply_queue))
            elif kind == "ecu.info":
                ecu_stage = self.session.ecu
                self._ack(
                    "ecu.info",
                    request_id,
                    profile_id=ecu_stage.profile_id,
                    ecu_state=ecu_stage.ecu_state,
                    fuel_mismatch_suspected=ecu_stage.fuel_mismatch_suspected,
                    calibration_hash=self.calibration_hash,
                )
            elif kind == "engine.restore":
                self._cmd_restore(request_id)
            elif kind == "hardware.install":
                self._cmd_install(command)
            elif kind == "engine.health":
                self._cmd_health(request_id, bool(command.get("include_failures", True)))
            elif kind == "operator.throttle":
                self._cmd_throttle(command)
            elif kind == "telemetry.config":
                self._cmd_telemetry_config(command)
            else:
                self._ack(str(kind), request_id, ok=False, code="COMMAND_UNKNOWN")
        except Exception as exc:  # comando inválido não derruba o laço
            worker_log().warning(
                "dyno.command_failed",
                command=str(kind),
                detail=f"{type(exc).__name__}: {exc}"[:200],
            )
            self._ack(str(kind), request_id, ok=False, code="COMMAND_FAILED", detail=str(exc)[:200])

    def _cmd_run_start(self, command: dict[str, object]) -> None:
        self.paused = False
        parts = self.session
        run_id = str(command.get("run_id"))
        if self.run_active:
            self._ack("run.start", run_id, ok=False, code="RUN_IN_PROGRESS")
            return
        if self._main_damage is not None and self._main_damage.engine_locked:
            self._ack("run.start", run_id, ok=False, code="ENGINE_DESTROYED")
            return
        request = DynoRunRequest.model_validate(command.get("request"))
        limits = parts.vehicle.mechanical_limits
        payload = parts.payload
        ctx = RunContext(
            session_id=payload.session_id,
            run_id=run_id,
            request=request,
            sim_hz=self.sim_hz,
            driveline=parts.driveline,
            rig=payload.rig,
            end_rpm=request.effective_end_rpm(float(limits.rev_limit_rpm)),
            idle_rpm=payload.idle_rpm,
            egt_limit_c=float(limits.egt_max_c),
            egt_abort_enabled=payload.egt_abort_enabled,
            egt_abort_margin_c=payload.egt_abort_margin_c,
            operator_protection=payload.operator_protection,
            correction=parts.correction,
            calibration_id=self.calibration_id,
            calibration_hash=self.calibration_hash,
            seed=payload.seed,
            started_at_tick=self.tick_index,
        )
        self.probe = request.probe
        if request.probe is not None:
            parts.damage = parts.make_damage(damage_enabled=False)
            parts.ecu.set_knock_open_loop(request.probe.knock_control_open_loop)
            self._bind_spectrum()
        parts.damage.set_run(run_id)
        self.run = RunController(ctx)
        self.run.start(self.tick_index, self.t_sim_s)
        self._errors_in_run = 0
        self._warnings_in_run = 0
        self.post_coast = False
        self._flush_run_states()
        self._ack("run.start", run_id, ok=True, started_at_tick=self.tick_index)

    def _cmd_run_abort(self, command: dict[str, object]) -> None:
        run_id = command.get("run_id")
        reason = AbortReason(str(command.get("reason", AbortReason.USER_ABORT.value)))
        if self.run is None or not self.run_active or (run_id and run_id != self.run.ctx.run_id):
            self._ack("run.abort", run_id, ok=False, code="RUN_NOT_ACTIVE")
            return
        self.run.request_abort(reason)
        self._ack("run.abort", run_id, ok=True)

    def _cmd_restore(self, request_id: object) -> None:
        self.paused = False
        parts = self.session
        if self.run_active:
            self._ack("engine.restore", request_id, ok=False, code="RUN_IN_PROGRESS")
            return
        damage = self._main_damage or parts.damage
        damage.restore()
        parts.physics.reset_mechanical()
        parts.rig.engage(0, 0.0)
        parts.physics.crank(parts.payload.idle_rpm)
        self.post_coast = False
        self._ack(
            "engine.restore",
            request_id,
            ok=True,
            health=damage.engine_health().model_dump(mode="json"),
            rod_weights=damage.rod_weights,
        )

    def _cmd_install(self, command: dict[str, object]) -> None:
        """Peças novas na fronteira de tick; o tempo da sessão continua (``tick_index``)."""
        request_id = command.get("request_id")
        if self.run_active:
            self._ack("hardware.install", request_id, ok=False, code="RUN_IN_PROGRESS")
            return
        parts = install_hardware(
            self.session,
            VehicleSpec.model_validate(command.get("vehicle")),
            exhaust_backpressure_scale=_number(command, "exhaust_backpressure_scale"),
            fuel_pump_capacity_scale=_number(command, "fuel_pump_capacity_scale"),
        )
        self._main_damage = parts.damage
        self._bind_spectrum()
        self.probe = None
        self.operator_pedal = 0.0
        self.pedal = 0.0
        self.post_coast = False
        self.last_state = None
        parts.rig.engage(0, 0.0)
        tick = self.tick_index
        parts.physics.crank(parts.payload.idle_rpm)
        self._warmup(INSTALL_WARMUP_S)
        # O aquecimento usa o relógio da física nova: a sessão segue no mesmo tick.
        parts.physics.vars.tick = tick
        self.tick_index = tick
        self._ack(
            "hardware.install",
            request_id,
            ok=True,
            health=parts.damage.engine_health().model_dump(mode="json"),
            rod_weights=parts.damage.rod_weights,
        )

    def _cmd_health(self, request_id: object, include_failures: bool) -> None:
        damage = self._main_damage or self.session.damage
        self._ack(
            "engine.health",
            request_id,
            ok=True,
            health=damage.engine_health(include_failures=include_failures).model_dump(mode="json"),
            rod_weights=damage.rod_weights,
        )

    def _cmd_throttle(self, command: dict[str, object]) -> None:
        value = command.get("throttle_pct")
        if self.run_active:
            self._ws_error("THROTTLE_LOCKED_BY_RUN", "Acelerador bloqueado durante a puxada.")
            return
        if isinstance(value, int | float):
            self.operator_pedal = min(max(float(value), 0.0), 100.0)
            self.paused = False

    # ------------------------------------------------------------------ tick
    def tick(self) -> None:
        if self.paused:
            self._hold()
            return
        speedup = 1
        if self.run is not None and self.run_active and self.run.phase == "cooldown":
            speedup = self.run.plan(self.t_sim_s).speedup
        # Arrefecimento acelerado (T031): ``speedup`` passos de ``dt`` num tick não são tempo
        # real por definição; o laço só conta overrun acima de ``speedup · dt`` de parede.
        # A física (número e ordem dos passos) não depende do relógio.
        self.wall_budget_ticks = speedup
        for _ in range(self.steps_per_tick * speedup):
            self.step()

    def _hold(self) -> None:
        """Espera determinística antes do 1.º comando de condução (sem avançar o tempo).

        A sessão nasce em marcha lenta estabilizada (``_warmup``) e só começa a avançar com
        ``run.start``, ``operator.throttle`` ou ``engine.restore``: assim a primeira puxada
        arranca sempre no mesmo tick e a mesma ``seed`` reproduz o hash da curva (RF-23),
        qualquer que seja o atraso entre o ``POST /sessions`` e o ``POST .../runs``.
        Calibrações aplicadas na espera entram na fronteira do primeiro passo.
        """
        self._process_apply_queue()
        self._emit_apply_acks(self.t_sim_s, self.t_sim_s)

    def _emit_apply_acks(self, t: float, t_emit: float) -> None:
        if not self._apply_acks:
            return
        parts = self.session
        runtime = parts.ecu.runtime
        applied = runtime.applied_t_sim_s if runtime is not None else None
        for ack in self._apply_acks:
            payload = {
                **ack,
                "ok": True,
                "applied_t_sim_s": t if applied is None or self.paused else applied,
                "fuel_mismatch_suspected": parts.ecu.fuel_mismatch_suspected,
            }
            self._emit("ack", payload, t_emit)
        self._apply_acks = []

    def step(self) -> None:
        """Um passo ``dt`` na ordem do contrato (sensors → ecu → physics → damage → telemetry)."""
        try:
            self._step()
        except Exception as exc:
            self._internal_error(exc)

    def _process_apply_queue(self) -> None:
        """``calibration.apply``/``ecu.swap`` na fronteira de tick (antes do passo 1)."""
        if not self._apply_queue:
            return
        parts = self.session
        queue, self._apply_queue = self._apply_queue, []
        for command in queue:
            kind = str(command.get("type"))
            try:
                if kind == "ecu.swap":
                    stage, ack = swap_ecu_stage(parts.payload, command)
                    parts.ecu = stage
                    runtime = stage.runtime
                    if runtime is not None:
                        runtime.reset_session()
                else:
                    ack = parts.ecu.apply_calibration(command)
            except Exception as exc:
                self._ack(
                    kind,
                    command.get("request_id"),
                    ok=False,
                    code="CALIBRATION_INVALID",
                    detail=f"{type(exc).__name__}: {exc}"[:200],
                )
                continue
            content_hash = command.get("content_hash")
            if isinstance(content_hash, str) and len(content_hash) == 64:  # noqa: PLR2004
                self.calibration_hash = content_hash
            calibration_id = command.get("calibration_id")
            if isinstance(calibration_id, str) and calibration_id:
                self.calibration_id = calibration_id
            self._apply_acks.append(ack)

    def _plan(self, t: float) -> TickPlan:
        parts = self.session
        if self.run is not None and self.run_active:
            return self.run.plan(t)
        if self.post_coast:
            target = parts.payload.idle_rpm + COASTDOWN_ABOVE_IDLE_RPM
            if parts.rig.coupled and parts.physics.rpm > target:
                return TickPlan(
                    parts.rig.gear,
                    0.0,
                    "hold",
                    rpm_ref=target,
                    fan_m_s=parts.payload.rig.fan_air_speed_m_s,
                )
            self.post_coast = False
        return TickPlan(0, self.operator_pedal, "free", fan_m_s=parts.payload.rig.fan_air_speed_m_s)

    def _step(self) -> None:  # noqa: PLR0912, PLR0915 - ordem do tick do contrato num só passo
        parts = self.session
        k = self.tick_index
        t = k / self.sim_hz
        dt = self.dt
        self._process_apply_queue()
        run = self.run
        if run is not None and self.run_active:
            run.begin_tick(k)
            self._flush_run_states()
            if run.terminal:
                self._finalize_run()
        plan = self._plan(t)
        if self.run is not None and self.run_active and not self.run.request.fan_on:
            plan.fan_m_s = 0.0
        physics = parts.physics
        rig = parts.rig
        if self.run is not None and self.run_active and self.run.consume_spin_up():
            self._spin_up(plan)
        if plan.gear != rig.gear:
            rig.engage(plan.gear, physics.rpm)
        mode = f"{plan.absorber}:{plan.gear}:{plan.measure_tag}"
        if mode != self._last_mode:
            assert self._rpm_ctl is not None  # noqa: S101
            self._rpm_ctl.reset()
            if self._load_ctl is not None:
                self._load_ctl.reset()
            if plan.measure_tag is None and self.window is not None:
                self.window.reset()
            if plan.absorber == "free":
                rig.absorber.reset()  # puxada inercial: absorvedor solto (T_abs = 0)
            self._last_mode = mode
        damage = parts.damage
        # 1. sensors
        sensors = physics.read_sensors(damage.knock_signal())
        # 2. ecu (+ sonda depois da arbitragem)
        ecu = parts.ecu.step(sensors, dt)
        commands = ecu.commands
        if self.probe is not None and self.run_active:
            commands = apply_probe(commands, self.probe)
        # orquestração do dyno: pedal, absorvedor e DynoLoad
        pedal = plan.pedal_pct
        if plan.map_target_kpa is not None:
            assert self._load_ctl is not None  # noqa: S101
            pedal = self._load_ctl.pedal(
                map_kpa=sensors.map_kpa,
                map_target_kpa=plan.map_target_kpa,
                pedal_target_pct=None,
                dt=dt,
            )
        pedal = self._arming_pedal_limit(pedal, physics.rpm, plan.rpm_ref, dt)
        step_max = PEDAL_RATE_PCT_S * dt
        pedal = min(max(pedal, self.pedal - step_max), self.pedal + step_max)
        self.pedal = pedal
        brake = self.last_state.torque_nm if self.last_state is not None else 0.0
        absorber_cmd = 0.0
        if plan.absorber == "hold" and rig.coupled:
            assert self._rpm_ctl is not None  # noqa: S101
            omega = parts.driveline.roller_omega(physics.rpm, rig.gear)
            absorber_cmd = self._rpm_ctl.command(
                rpm=physics.rpm,
                rpm_ref=plan.rpm_ref,
                ref_rate_rpm_s=plan.ref_rate_rpm_s,
                gear=rig.gear,
                brake_torque_nm=brake,
                engine_inertia_kg_m2=physics.j_engine,
                loss_nm=rig.loss_torque(omega),
                capacity_nm=rig.absorber.capacity(omega),
                dt=dt,
            )
        load = rig.load(
            rpm=physics.rpm,
            brake_torque_nm=brake,
            absorber_command_nm=absorber_cmd,
            dt=dt,
            pedal_pct=pedal,
            fan_air_speed_m_s=plan.fan_m_s,
        )
        # 3. physics
        state = physics.step(commands, load, dt)
        # 4. damage
        dstate = damage.step(state, dt, ecu.status)
        # 5. telemetria, medição e máquina de estados
        omega_roll = rig.after_step(state.rpm)
        t_next = (k + 1) / self.sim_hz
        self._emit_apply_acks(t, t_next)
        run_id = self.run.ctx.run_id if self.run is not None and self.run_active else None
        parts.sampler.on_tick(
            TickRecord(
                tick=k,
                t_sim_s=t,
                sensors=sensors,
                commands=commands,
                ecu=ecu,
                state=state,
                damage=dstate,
                load=load,
                run_id=run_id,
                absorber_nm=rig.last_absorber_nm,
                roller_speed_kmh=rig.vehicle_speed_kmh(),
                real_time_factor=self.real_time_factor,
            )
        )
        for failure in dstate.new_failures:
            self._emit("event.failure", failure.model_dump(mode="json"), t)
            if not failure.catastrophic:
                self._warnings_in_run += 1
        for knock in damage.knock_events:
            self._emit("event.knock", knock.payload(), knock.t_sim_s)
        self._limiter_events(ecu, state, run_id, t)
        measured = self._measure(
            plan=plan,
            sensors=sensors,
            state=state,
            ecu=ecu,
            pedal=pedal,
            omega_roll=omega_roll,
            t=t,
        )
        self.last_state = state
        self.last_ecu = ecu
        self.tick_index = k + 1
        if self.run is not None and self.run_active:
            self.run.observe(
                TickObservation(
                    tick=k,
                    t_sim_s=t,
                    rpm=state.rpm,
                    egt_c=sensors.egt_collector_c,
                    map_kpa=sensors.map_kpa,
                    limiter_active=ecu.status.limiter_state != "off",
                    absorber_nm=rig.last_absorber_nm,
                    failures=list(dstate.new_failures),
                    knock_last=list(dstate.knock_last),
                    knock_events=len(damage.knock_events),
                    measured=measured,
                )
            )
            self._flush_run_states()
            if self.run.terminal:
                self._finalize_run()

    def _arming_pedal_limit(self, pedal: float, rpm: float, rpm_ref: float, dt: float) -> float:
        """Limitador de pedal do arming: o absorvedor tem de conseguir segurar a ``start_rpm``.

        Motores com torque na roda acima da capacidade ``T_max(ω)`` do absorvedor na
        ``start_rpm`` (coupé 500 N·m e V8 650 N·m em 4.ª a 2000 rpm) não estabilizam a plena
        carga e o arming excederia os 10 s. Com o absorvedor saturado (≥ 97 % de ``T_max``)
        e a rotação acima da referência, o teto do pedal desce a 40 %/s; abaixo de 85 % de
        ``T_max`` sobe a 10 %/s até ao pedido (entre os dois fica fixo, sem ciclo limite).
        Fora do arming o teto é 100 % (a puxada usa o pedal do pedido).
        """
        run = self.run
        rig = self.session.rig
        if run is None or not self.run_active or run.phase != "arming" or not rig.coupled:
            self.arming_pedal_cap = 100.0
            return pedal
        omega = self.session.driveline.roller_omega(rpm, rig.gear)
        capacity = rig.absorber.capacity(omega)
        absorbed = rig.last_absorber_nm
        if absorbed >= ARMING_SATURATION_RATIO * capacity and rpm > rpm_ref:
            step = ARMING_PEDAL_CAP_RATE_PCT_S * dt
            self.arming_pedal_cap = max(0.0, self.arming_pedal_cap - step)
        elif absorbed < ARMING_RELEASE_RATIO * capacity:
            step = ARMING_PEDAL_CAP_RELEASE_PCT_S * dt
            self.arming_pedal_cap = min(100.0, self.arming_pedal_cap + step)
        return min(pedal, self.arming_pedal_cap)

    def _spin_up(self, plan: TickPlan) -> None:
        """Acionamento da bancada (EC-06 da física): leva motor e rolo à ``start_rpm``.

        Sem isto o motor teria de acelerar a inércia do rolo desde a marcha lenta (≈ 6 s em
        4.ª marcha) ou o absorvedor teria de frear um motor acima da ``start_rpm``, e o arming
        das marchas altas excederia os 10 s. O transitório de
        aceleração do conjunto não é medido; o arming continua a exigir 1,0 s estável.
        """
        physics = self.session.physics
        if not physics.vars.locked and abs(physics.rpm - plan.rpm_ref) > 25.0:  # noqa: PLR2004
            physics.crank(plan.rpm_ref)
            if self.last_state is not None:
                self.last_state = self.last_state.model_copy(update={"rpm": physics.rpm})
        self.session.rig.engage(plan.gear, physics.rpm)

    def _measure(
        self,
        *,
        plan: TickPlan,
        sensors: SensorReadings,
        state: EngineState,
        ecu: EcuStepResult,
        pedal: float,
        omega_roll: float,
        t: float,
    ) -> MeasuredSample | None:
        if plan.measure_tag is None or self.window is None or not self.session.rig.coupled:
            return None
        rig = self.session.rig
        ign = state.ignition_advance_deg
        centre = _Centre(
            tag=plan.measure_tag,
            gear=rig.gear,
            rpm=state.rpm,
            t_sim_s=t,
            absorber_nm=rig.last_absorber_nm,
            loss_nm=rig.last_loss_nm,
            lambda_=sensors.lambda_measured,
            egt_c=sensors.egt_collector_c,
            map_kpa=sensors.map_kpa,
            iat_c=sensors.iat_c,
            ect_c=sensors.ect_c,
            oil_c=sensors.oil_temp_c,
            ignition_deg=sum(ign) / len(ign) if ign else 0.0,
            knock_retard=max(ecu.status.knock_retard_deg, default=0.0),
            pedal_pct=pedal,
        )
        out = self.window.push(omega_roll, centre)
        if out is None:
            return None
        alpha, c = out
        dl = self.session.driveline
        g = dl.overall_ratio(c.gear)
        omega_c = dl.roller_omega(c.rpm, c.gear)
        m = measure_roll(
            roller_inertia_kg_m2=rig.roller_inertia,
            omega_roll=omega_c,
            alpha_roll=alpha,
            absorber_nm=c.absorber_nm,
            loss_nm=c.loss_nm,
            overall_ratio=g,
            k=dl.k,
            efficiency=dl.efficiency,
        )
        afr = c.lambda_ * self.session.fuel.afr_stoich
        sample = CurveSample(
            rpm=c.rpm,
            t_sim_s=c.t_sim_s,
            power_wheel_kw=m.power_wheel_kw,
            power_crank_kw=m.power_crank_w / 1000.0,
            torque_wheel_nm=m.torque_wheel_nm,
            torque_engine_nm=m.torque_engine_nm,
            lambda_=c.lambda_,
            afr=afr,
            egt_c=c.egt_c,
            map_kpa=c.map_kpa,
            iat_c=c.iat_c,
            ect_c=c.ect_c,
            oil_c=c.oil_c,
            ignition_deg_btdc=c.ignition_deg,
            knock_retard_max_deg=c.knock_retard,
            pedal_pct=c.pedal_pct,
        )
        return MeasuredSample(sample, c.tag)

    def _limiter_events(
        self, ecu: EcuStepResult, state: EngineState, run_id: str | None, t: float
    ) -> None:
        current = ecu.status.limiter_state
        if current == self.limiter_state:
            return
        active = current != "off"
        self._emit(
            "event.limiter",
            {
                "run_id": run_id,
                "kind": "rev_limiter",
                "phase": current if active else None,
                "active": active,
                "rpm": state.rpm,
            },
            t,
        )
        self.limiter_state = current

    # ------------------------------------------------------------------ fim de puxada
    def _flush_run_states(self) -> None:
        if self.run is None:
            return
        for payload in self.run.drain():
            self._emit("run.state", payload.model_dump(mode="json"))

    def _finalize_run(self) -> None:
        run = self.run
        if run is None:
            return
        parts = self.session
        result = run.result()
        damage = parts.damage
        main = self._main_damage or damage
        kind: str | None = None
        if result.state == RunState.ENGINE_FAILED:
            kind = "failure"
        elif self._warnings_in_run > 0 and run.request.probe is None:
            kind = "near_miss"
        if kind is not None:
            self._emit(
                "damage.trace",
                {
                    "run_id": result.run_id,
                    "kind": kind,
                    "trace": encode_trace(damage.freeze_trace()),
                },
            )
        failures = [f for f in damage.failures if f.run_id == result.run_id]
        self._emit(
            "run.result",
            {
                "run": result.model_dump(mode="json", by_alias=True),
                "engine_locked": main.engine_locked,
                "health": main.engine_health(include_failures=False).model_dump(mode="json"),
                "rod_weights": main.rod_weights,
                "failures": [f.model_dump(mode="json") for f in failures],
                "is_baseline": result.run_type == RunType.BASELINE_PULL
                and result.state == RunState.COMPLETED,
            },
        )
        damage.set_run(None)
        if self.probe is not None:
            parts.ecu.set_knock_open_loop(False)
            parts.damage = main
            self._bind_spectrum()
            self.probe = None
        self.run = None
        self.post_coast = result.state != RunState.ENGINE_FAILED
        self._last_mode = ""

    def _internal_error(self, exc: BaseException) -> None:
        detail = f"{type(exc).__name__}: {exc}"[:200]
        worker_log().error(
            "dyno.tick_exception",
            detail=detail,
            t_sim_s=self.t_sim_s,
            trace=traceback.format_exc(limit=8)[-1500:],
        )
        if self._errors_in_run < _MAX_ERRORS_PER_RUN:
            self._ws_error("SIM_INTERNAL_ERROR", detail)
        self._errors_in_run += 1
        if self.parts is not None:
            self.tick_index = round(self.parts.physics.t_sim_s * self.sim_hz)
        if self.run is not None and self.run_active:
            self.run.add_event("internal_error")
            self.run.fail_now(AbortReason.INTERNAL_ERROR, self.tick_index)
            self._flush_run_states()
            self._finalize_run()


def vehicle_gears(vehicle: VehicleSpec) -> int:
    """Número de marchas do veículo (``GEAR_NOT_AVAILABLE``)."""
    return len(vehicle.gear_ratios)
