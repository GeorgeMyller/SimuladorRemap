"""``EcuRuntime``: pipeline da ECU genérica por tick.

Fontes: ecu-core RF-27, RF-29, RF-30, RF-33; D-18; simulation-bus 3.2.

Ordem obrigatória do ``step()`` (Apêndice D):

1. validar sensores e substituir falhas (EC-04, EC-15);
2. eixos de carga (``map_kpa``, ``tps_pct``, ``load_pct``, ...) no vetor ``inputs``;
3. massa de ar (modo do ``fuel_model``; ``ProfileHooks.air_charge_mg`` em
   ``profile_air_model``) e lambda alvo base;
4. compensações, malha fechada e trims por cilindro;
5. avanço base, correções e knock control;
6. alvo de boost (tabela, teto por marcha, teto do knock);
7. pedidos de failsafe (com overboost), limitador, two-step, antilag, powershift e
   overrun; ``ProfileHooks.adjust_requests``;
8. arbitragem, lambda final, pulso e duty de injeção, duty da wastegate, clamps e
   escrita de ``ActuatorCommands``, ``EcuStatus`` e ``EcuEvent``.

Came variável (002 RF-11): os alvos das tabelas de came passam pela estratégia ``vvt``
(inibição a frio, offsets, limite de taxa); sem ela valem as tabelas (RF-31).

Flex (002 RF-18): com ``SensorReadings.ethanol_pct`` presente, a massa de combustível é
escalada por ``AFR_stock / AFR_blend(etanol lido)`` e o tempo de abertura do bico ainda por
``ρ_stock / ρ_blend`` (o bico mede volume); as tabelas opcionais ``flex_ign_add`` e
``flex_boost_add`` somam-se ao avanço e ao alvo de boost. Sem sensor nada muda.

Determinismo (RNF-02): sem relógio de parede nem aleatoriedade; tempos derivam de
``SensorReadings.t_sim_s`` e ``dt``; o padrão de corte rotativo usa o contador de ciclos
calculado pela integração da RPM. O hot path usa listas Python, ``bisect`` e
``model_construct`` (sem validação Pydantic por tick).

Troca de calibração (RF-27): ``swap_calibration`` deixa a calibração pendente; ela entra
em vigor no início do próximo ``step()`` (fronteira de tick), inteira. Em
``live_tables`` só as tabelas mudam e os integradores (PI, PID) e o retardo de knock
continuam; em ``full`` as estratégias são reconstruídas, preservando o LTFT e o retardo
de knock da sessão.
"""

from __future__ import annotations

from math import inf, isfinite, isnan
from typing import Any, Final, Literal

from simremap.core.native import native
from simremap.ecu.arbitration import ArbitrationResult, EcuRequests, arbitrate
from simremap.ecu.compiled import (
    QUANTITY_INDEX,
    CompiledCalibration,
    CompiledTable,
    EcuHardwareConfig,
    compile_calibration,
)
from simremap.ecu.contracts import (
    AntilagConfig,
    AxisQuantity,
    BoostControlConfig,
    ClosedLoopConfig,
    EcuEvent,
    EcuStatus,
    EcuStepResult,
    FailsafeConfig,
    KnockControlConfig,
    OverrunConfig,
    PowershiftConfig,
    RevLimiterConfig,
    StrategyConfig,
    TableKind,
    TwoStepConfig,
    VvtConfig,
)
from simremap.ecu.hooks import NullProfileHooks, ProfileHooks
from simremap.ecu.limits import (
    FLEX_AFR_E27,
    FLEX_AFR_E100,
    FLEX_DENSITY_E27_G_CC,
    FLEX_DENSITY_E100_G_CC,
    IGNITION_MAX_DEG,
    IGNITION_MIN_DEG,
    MAP_FALLBACK_KPA,
    MAP_VALID_MAX_KPA,
    MAP_VALID_MIN_KPA,
    PW_MAX_MS,
    SENSOR_HOLD_S,
    TEMP_MAX_C,
    TEMP_MIN_C,
)
from simremap.ecu.native_tables import NativeTablePlan
from simremap.ecu.strategies import (
    Antilag,
    BoostControl,
    ClosedLoop,
    Failsafe,
    FuelStrategy,
    Ignition,
    KnockControl,
    Overrun,
    Powershift,
    RevLimiter,
    TickContext,
    TwoStep,
)
from simremap.ecu.strategies.vvt import VvtControl
from simremap.physics.contracts import ActuatorCommands, SensorReadings
from simremap.physics.fuel_blend import blend_afr_stoich, blend_density

__all__ = [
    "BUDGET_OVERRUN_EVENT_EVERY",
    "STEP_BUDGET_MAX_S",
    "CompiledCalibration",
    "EcuHardwareConfig",
    "EcuRuntime",
    "NullProfileHooks",
    "ProfileHooks",
    "compile_calibration",
]

STEP_BUDGET_MAX_S: Final = 0.0005  # s: estouro de orçamento (EC-12)
BUDGET_OVERRUN_EVENT_EVERY: Final = 1000
BYPASS_TPS_MAX_PCT: Final = 5.0  # % de borboleta abaixo do qual a BOV/bypass pode abrir
BYPASS_DELTA_KPA: Final = 10.0  # kPa de diferença que abre a BOV/bypass
TPS_RATE_DEADBAND_PCT: Final = 0.4  # % de banda morta do dTPS/dt (4σ do ruído do TPS)

_Q = QUANTITY_INDEX
_I_RPM = _Q[AxisQuantity.RPM]
_I_MAP = _Q[AxisQuantity.MAP_KPA]
_I_TPS = _Q[AxisQuantity.TPS_PCT]
_I_PEDAL = _Q[AxisQuantity.PEDAL_PCT]
_I_LOAD = _Q[AxisQuantity.LOAD_PCT]
_I_ECT = _Q[AxisQuantity.ECT_C]
_I_IAT = _Q[AxisQuantity.IAT_C]
_I_BAT = _Q[AxisQuantity.BATTERY_V]
_I_GEAR = _Q[AxisQuantity.GEAR]
_I_EGT = _Q[AxisQuantity.EGT_C]
_I_RATE = _Q[AxisQuantity.TPS_RATE_PCT_S]
_I_BOOST = _Q[AxisQuantity.BOOST_TARGET_KPA]
_I_TORQUE = _Q[AxisQuantity.TORQUE_NM]
_I_ETHANOL = _Q[AxisQuantity.ETHANOL_PCT]
_K = TableKind


class _SensorGuard:
    """Último valor válido e tempo em falha de um canal (EC-04, EC-15)."""

    __slots__ = ("bad_since", "fault", "last")

    def __init__(self, initial: float) -> None:
        self.last = initial
        self.bad_since = inf
        self.fault = False

    def ok(self, value: float) -> float:
        self.last = value
        self.bad_since = inf
        self.fault = False
        return value

    def bad(self, t: float) -> bool:
        """Regista a falha; devolve ``True`` quando passou ``SENSOR_HOLD_S``."""
        if self.bad_since == inf:
            self.bad_since = t
        self.fault = t - self.bad_since >= SENSOR_HOLD_S - 1e-9
        return self.fault


class EcuRuntime:
    """Runtime genérico da ECU (um por sessão; corre só no worker do laço)."""

    def __init__(
        self,
        compiled: CompiledCalibration,
        hooks: ProfileHooks | None = None,
        hardware: EcuHardwareConfig | None = None,
        *,
        enabled_strategies: frozenset[str] | None = None,
    ) -> None:
        hw = hardware
        if hw is None:
            raise ValueError("EcuRuntime exige EcuHardwareConfig")
        if hw.n_cyl != compiled.n_cyl:
            raise ValueError("n_cyl da calibração compilada difere do hardware")
        self.hardware = hw
        self.hooks: ProfileHooks = hooks if hooks is not None else NullProfileHooks()
        self.enabled_strategies = enabled_strategies
        self.n_cyl = hw.n_cyl
        self.compiled = compiled
        self.ctx = TickContext(hw.n_cyl)
        self.requests = EcuRequests(hw.n_cyl)
        self.result = ArbitrationResult(hw.n_cyl)
        self.fuel = FuelStrategy(compiled, hw)
        knock_cfg = self._cfg(compiled, "knock_control", KnockControlConfig)
        self.knock = KnockControl(knock_cfg, hw.n_cyl)
        self.ignition = Ignition(compiled, self.knock)
        self.closed_loop = ClosedLoop(self._cfg(compiled, "closed_loop", ClosedLoopConfig))
        boost_cfg = self._cfg(compiled, "boost_control", BoostControlConfig)
        self.boost = BoostControl(boost_cfg, compiled)
        self._build_arbitrated(compiled)
        self.vvt = VvtControl(self._cfg(compiled, "vvt", VvtConfig))
        self._map = _SensorGuard(101.325)
        self._iat = _SensorGuard(20.0)
        self._ect = _SensorGuard(20.0)
        self._sensor_fault = False
        self._tps_prev = -1.0
        self._tps_prev_t = 0.0
        self._tps_raw1 = -1.0
        self._tps_raw2 = -1.0
        self._crank_accum = 0.0
        self._duty_high = False
        self._duty_warn = False
        self._pending: tuple[CompiledCalibration, Literal["full", "live_tables"]] | None = None
        self.applied_t_sim_s: float | None = None
        self.budget_overruns = 0
        self._budget_event_due = False
        self.last_lambda_target = 1.0
        self._first_tick = True
        mod = native()
        self._native_tables: Any = mod.tables if mod is not None else None
        self._plan: NativeTablePlan | None = None

    # ------------------------------------------------------------------ configuração

    def _cfg[T: StrategyConfig](
        self, compiled: CompiledCalibration, kind: str, model: type[T]
    ) -> T | None:
        cfg = compiled.strategies.get(kind)
        if cfg is None or not isinstance(cfg, model):
            return None
        if self.enabled_strategies is not None and kind not in self.enabled_strategies:
            return None
        if kind not in self.hooks.supported_strategies():
            return None
        return cfg

    def _build_arbitrated(self, compiled: CompiledCalibration) -> None:
        self.failsafe = Failsafe(self._cfg(compiled, "failsafe", FailsafeConfig), compiled)
        self.rev_limiter = RevLimiter(self._cfg(compiled, "rev_limiter", RevLimiterConfig))
        self.two_step = TwoStep(self._cfg(compiled, "two_step", TwoStepConfig))
        self.antilag = Antilag(self._cfg(compiled, "antilag", AntilagConfig))
        self.powershift = Powershift(self._cfg(compiled, "powershift", PowershiftConfig))
        self.overrun = Overrun(self._cfg(compiled, "overrun", OverrunConfig))

    def swap_calibration(
        self, compiled: CompiledCalibration, mode: Literal["full", "live_tables"] = "full"
    ) -> None:
        """Agenda a troca para a próxima fronteira de tick (RF-27, Fluxo A)."""
        if compiled.n_cyl != self.n_cyl:
            raise ValueError("n_cyl da nova calibração difere do runtime")
        if mode == "live_tables" and compiled.strategies != self.compiled.strategies:
            raise ValueError("live_tables não pode alterar estratégias")
        self._pending = (compiled, mode)

    @property
    def swap_pending(self) -> bool:
        return self._pending is not None

    def _apply_pending(self, t: float) -> None:
        if self._pending is None:  # pragma: no cover - chamado só com pendente
            return
        compiled, mode = self._pending
        self._pending = None
        self.compiled = compiled
        for part in (self.fuel, self.ignition, self.boost, self.failsafe):
            part.set_compiled(compiled)
        if mode == "full":
            self.knock.configure(self._cfg(compiled, "knock_control", KnockControlConfig))
            self.closed_loop.configure(self._cfg(compiled, "closed_loop", ClosedLoopConfig))
            self.boost.configure(self._cfg(compiled, "boost_control", BoostControlConfig))
            self.vvt.configure(self._cfg(compiled, "vvt", VvtConfig))
            self._build_arbitrated(compiled)
        self.applied_t_sim_s = t

    def set_knock_open_loop(self, enabled: bool) -> None:
        """Sondas (``ProbeOverrides.knock_control_open_loop``): retardo de knock fixo em 0°."""
        self.knock.open_loop = enabled

    def reset_session(self) -> None:
        """Reinicia o estado da sessão (LTFT a zero, premissa OQ-05)."""
        self.closed_loop.reset_session()
        self.fuel.reset_session()

    def record_step_duration(self, seconds: float) -> None:
        """Contagem de estouros (> 0,5 ms) medida pelo worker (EC-12)."""
        if seconds > STEP_BUDGET_MAX_S:
            self.budget_overruns += 1
            if self.budget_overruns % BUDGET_OVERRUN_EVENT_EVERY == 0:
                self._budget_event_due = True

    # ------------------------------------------------------------------ passo 1

    def _read_sensors(self, s: SensorReadings, ctx: TickContext) -> None:
        t = ctx.t
        rpm = s.rpm
        ctx.rpm = rpm if isfinite(rpm) and rpm > 0.0 else 0.0
        baro = s.baro_kpa
        ctx.baro_kpa = baro if isfinite(baro) and baro > 0.0 else 101.325

        m = s.map_kpa
        if isfinite(m) and MAP_VALID_MIN_KPA <= m <= MAP_VALID_MAX_KPA:
            ctx.map_kpa = self._map.ok(m)
        elif self._map.bad(t):
            ctx.map_kpa = MAP_FALLBACK_KPA
        else:
            ctx.map_kpa = self._map.last
        ctx.iat_c = self._temp(self._iat, s.iat_c, t)
        ctx.ect_c = self._temp(self._ect, s.ect_c, t)
        fault = self._map.fault or self._iat.fault or self._ect.fault
        if fault and not self._sensor_fault:
            channel = "map_kpa" if self._map.fault else ("iat_c" if self._iat.fault else "ect_c")
            ctx.emit("sensor_fault", detail=channel)
        self._sensor_fault = fault
        ctx.sensor_fault = fault

        tps = s.tps_pct
        tps = 0.0 if not isfinite(tps) or tps < 0.0 else (100.0 if tps > 100.0 else tps)  # noqa: PLR2004
        # dTPS/dt com banda morta (RF-08): o valor retido só muda quando o TPS se afasta mais
        # de TPS_RATE_DEADBAND_PCT e a taxa usa o tempo desde a última mudança. Sem isto o
        # ruído do sensor (σ 0,1 % a 1 kHz ⇒ ≈ 140 %/s) mantinha o enriquecimento de
        # aceleração em ~30 % em regime permanente. A taxa usa a mediana das 3 últimas
        # amostras (B1, 003 T032): uma amostra isolada além da banda morta (cauda de 4σ, a
        # cada ~30 000 amostras; a 100 % o ruído recortado só desce) e o regresso no tick
        # seguinte davam ~450 %/s e +36 % de combustível em plena carga.
        ctx.tps_rate_pct_s = self._tps_rate(self._tps_median(tps), t, ctx.dt)
        ctx.tps_pct = tps
        ctx.pedal_pct = s.pedal_pct
        lam = s.lambda_measured
        ctx.lambda_valid = lam is not None and isfinite(lam) and 0.5 <= lam <= 2.0  # noqa: PLR2004
        ctx.lambda_measured = lam if ctx.lambda_valid else 1.0
        ctx.egt_c = s.egt_collector_c
        bat = s.battery_v
        ctx.battery_v = bat if isfinite(bat) else 14.0
        ctx.oil_pressure_kpa = s.oil_pressure_kpa
        ctx.fuel_pressure_kpa = s.fuel_pressure_kpa
        ctx.gear = s.gear
        ctx.vehicle_speed_kmh = s.vehicle_speed_kmh
        ctx.clutch_pressed = s.clutch_pressed
        ctx.launch_switch = s.launch_switch
        ctx.shift_request = s.shift_request
        ctx.antilag_switch = s.antilag_switch
        knock = s.knock_intensity
        dst = ctx.knock_intensity
        for k in range(self.n_cyl):
            dst[k] = knock[k]
        # Contador de ciclos (720° por ciclo) para os padrões de corte rotativos.
        self._crank_accum += ctx.rpm * 6.0 * ctx.dt / 720.0
        ctx.cycle_counter = int(self._crank_accum)

    def _tps_median(self, tps: float) -> float:
        """Mediana de 3 do TPS (a 1.ª leitura preenche o histórico; 1 tick de atraso)."""
        a = self._tps_raw2
        b = self._tps_raw1
        if a < 0.0:
            a = b = tps
        self._tps_raw2 = b
        self._tps_raw1 = tps
        if a > b:
            a, b = b, a
        return a if tps < a else (b if tps > b else tps)

    def _tps_rate(self, tps: float, t: float, dt: float) -> float:
        """dTPS/dt com banda morta (ver ``TPS_RATE_DEADBAND_PCT``)."""
        prev = self._tps_prev
        if prev < 0.0:
            self._tps_prev = tps
            self._tps_prev_t = t
            return 0.0
        if abs(tps - prev) <= TPS_RATE_DEADBAND_PCT:
            return 0.0
        elapsed = t - self._tps_prev_t
        self._tps_prev = tps
        self._tps_prev_t = t
        return (tps - prev) / (elapsed if elapsed > dt else dt)

    @staticmethod
    def _bypass_open(ctx: TickContext, pre_throttle_kpa: float) -> bool:
        """BOV/bypass com a borboleta fechada (B4, 003 T032).

        Referenciada ao coletor como uma diverter real: abre quando a pressão antes da
        borboleta passa o MAP em ``BYPASS_DELTA_KPA`` (no coastdown o MAP cai a 8–20 kPa e
        o critério antigo, MAP > baro + 10, nunca abria: surge do compressor até 7,3 s) ou,
        como antes, com o coletor pressurizado (compressor volumétrico antes da borboleta).
        """
        if ctx.tps_pct >= BYPASS_TPS_MAX_PCT:
            return False
        if ctx.map_kpa > ctx.baro_kpa + BYPASS_DELTA_KPA:
            return True
        return isfinite(pre_throttle_kpa) and pre_throttle_kpa > ctx.map_kpa + BYPASS_DELTA_KPA

    @staticmethod
    def _temp(guard: _SensorGuard, value: float, t: float) -> float:
        if isfinite(value) and TEMP_MIN_C <= value <= TEMP_MAX_C:
            return guard.ok(value)
        guard.bad(t)
        if not isfinite(value):
            return guard.last
        return TEMP_MIN_C if value < TEMP_MIN_C else TEMP_MAX_C

    # ------------------------------------------------------------------ nativo

    def _native_view(self, cal: CompiledCalibration) -> dict[TableKind, CompiledTable]:
        """Tabelas do tick pela extensão nativa (``native_tables``), após o hook de ar.

        A vista é refeita quando a calibração ativa muda (troca ou ``_bind`` do perfil OEM,
        que só ocorre dentro de ``air_charge_mg``, antes deste ponto).
        """
        plan = self._plan
        if plan is None or plan.source is not cal:
            plan = NativeTablePlan(cal, self._native_tables)
            self._plan = plan
            for part in (self.fuel, self.ignition, self.boost, self.failsafe):
                part.set_compiled(plan.view)
        plan.invalidate()
        return plan.view.tables

    # ------------------------------------------------------------------ flex

    def _flex_corrections(
        self, ethanol: float | None, inputs: list[float], tables: dict[TableKind, CompiledTable]
    ) -> tuple[float, float, float]:
        """``(fator de massa, fator de abertura, avanço somado)``; ``(1, 1, 0)`` sem sensor."""
        if ethanol is None:
            return 1.0, 1.0, 0.0
        hw = self.hardware
        ign_add = tables.get(_K.FLEX_IGN_ADD)
        adv = ign_add.at(inputs) if ign_add is not None else 0.0
        nt = self._native_tables
        if nt is not None:
            mass, opening = nt.flex_factors(
                ethanol,
                hw.afr_stoich,
                hw.fuel_density_g_cc,
                FLEX_AFR_E27,
                FLEX_AFR_E100,
                FLEX_DENSITY_E27_G_CC,
                FLEX_DENSITY_E100_G_CC,
            )
            return mass, opening, adv
        mass = hw.afr_stoich / blend_afr_stoich(ethanol, FLEX_AFR_E27, FLEX_AFR_E100)
        rho = blend_density(ethanol, FLEX_DENSITY_E27_G_CC, FLEX_DENSITY_E100_G_CC)
        return mass, mass * hw.fuel_density_g_cc / rho, adv

    # ------------------------------------------------------------------ step

    def step(  # noqa: PLR0912, PLR0915 - pipeline do Apêndice D num só passo (RNF-01)
        self, sensors: SensorReadings, dt: float
    ) -> EcuStepResult:
        """Converte ``SensorReadings`` em ``ActuatorCommands`` (+ ``EcuStatus`` e eventos)."""
        ctx = self.ctx
        ctx.t = sensors.t_sim_s
        ctx.dt = dt
        ctx.tick = sensors.tick
        ctx.events = []
        if self._pending is not None:
            self._apply_pending(ctx.t)
        if self._budget_event_due:
            self._budget_event_due = False
            ctx.emit("budget_overrun", value=float(self.budget_overruns))
        cal = self.compiled
        tables = cal.tables
        n = self.n_cyl

        # 1. sensores
        self._read_sensors(sensors, ctx)
        rpm = ctx.rpm

        # 2. eixos de carga
        load = 100.0 * ctx.map_kpa / ctx.baro_kpa
        load = 0.0 if load < 0.0 else (300.0 if load > 300.0 else load)  # noqa: PLR2004
        inputs = ctx.inputs
        inputs[_I_RPM] = rpm
        inputs[_I_MAP] = ctx.map_kpa
        inputs[_I_TPS] = ctx.tps_pct
        inputs[_I_PEDAL] = ctx.pedal_pct
        inputs[_I_LOAD] = load
        inputs[_I_ECT] = ctx.ect_c
        inputs[_I_IAT] = ctx.iat_c
        inputs[_I_BAT] = ctx.battery_v
        inputs[_I_GEAR] = float(ctx.gear)
        inputs[_I_EGT] = ctx.egt_c
        inputs[_I_RATE] = ctx.tps_rate_pct_s
        ethanol = sensors.ethanol_pct
        if ethanol is not None:
            inputs[_I_ETHANOL] = ethanol
        torque_req: float | None = None
        tq_table = tables.get(_K.TORQUE_REQUEST)
        if tq_table is not None and cal.profile_id == "oem-stage":
            torque_req = tq_table.at(inputs)
            inputs[_I_TORQUE] = torque_req

        # 3–4. combustível, compensações, malha fechada
        air_hook = (
            self.hooks.air_charge_mg(sensors, cal) if cal.fuel_mode == "profile_air_model" else None
        )
        if self._native_tables is not None:
            tables = self._native_view(cal)
        fuel = self.fuel
        fuel.prepare(ctx, air_hook)
        if self._first_tick:
            self._first_tick = False
            ctx.lambda_target_prev = fuel.lambda_base
        self.closed_loop.update(ctx, fuel.t_since_start)

        # 5. ignição e knock
        self.knock.update(ctx, self.ignition.threshold(ctx))
        self.ignition.compute(ctx, fuel.cranking)

        # 6. alvo de boost
        target = self.boost.target(ctx, self.knock.boost_ceiling_reduction(ctx.t))
        flex_boost = tables.get(_K.FLEX_BOOST_ADD) if ethanol is not None else None
        if flex_boost is not None:
            target += flex_boost.at(inputs)

        # 7. pedidos
        reqs = self.requests
        reqs.reset()
        self.failsafe.update(ctx, reqs.failsafe)
        self.boost.check_overboost(ctx, reqs.failsafe)
        self.rev_limiter.update(ctx, reqs.rev_limiter)
        self.two_step.update(ctx, reqs.two_step)
        self.antilag.update(ctx, reqs.antilag)
        self.powershift.update(ctx, reqs.powershift)
        self.overrun.update(ctx, reqs.overrun)
        self.hooks.adjust_requests(sensors, reqs)

        # 8. arbitragem e escrita
        res = self.result
        arbitrate(reqs, fuel.lambda_base, res)
        lam = res.lambda_target if not isnan(res.lambda_target) else fuel.lambda_base
        final_target = target if target <= res.boost_ceiling_kpa else res.boost_ceiling_kpa
        final_target = max(final_target, 0.0)
        inputs[_I_BOOST] = final_target
        duty_wg = self.boost.compute_duty(ctx, final_target, res.boost_cut)

        normal = self.ignition.adv
        override = res.ign_override
        retard = res.ign_retard
        has_override = not isnan(override)
        trim = self.closed_loop.trim_total
        fuel_cut = res.fuel_cut
        flex_mass, flex_open, flex_adv = self._flex_corrections(ethanol, inputs, tables)
        period_ms = 120000.0 / rpm if rpm > 0.0 else inf
        adv_out = [0.0] * n
        pw_out = [0.0] * n
        mass_out = [0.0] * n
        pw_max = 0.0
        clipped = False
        for k in range(n):
            a = normal[k]
            if has_override and override < a:
                a = override
            a -= retard
            a += flex_adv
            adv_out[k] = (
                IGNITION_MIN_DEG
                if a < IGNITION_MIN_DEG
                else (IGNITION_MAX_DEG if a > IGNITION_MAX_DEG else a)
            )
            if rpm <= 0.0 or fuel_cut[k]:
                continue
            mass, pw = fuel.pulse(k, lam, trim)
            if ethanol is not None and mass > 0.0:
                mass *= flex_mass
                pw = fuel.dead_time_ms + (pw - fuel.dead_time_ms) * flex_open
            if pw > period_ms:
                pw = period_ms
                clipped = True
            pw = min(pw, PW_MAX_MS)
            pw_out[k] = pw
            mass_out[k] = mass
            pw_max = max(pw_max, pw)
        duty = pw_max / period_ms * 100.0 if rpm > 0.0 else 0.0
        if clipped != self._duty_high:
            self._duty_high = clipped
            if clipped:
                ctx.emit("inj_duty_high", value=duty, detail="limitado a 100 %")
        warn = duty > cal.inj_duty_warn_pct
        if warn != self._duty_warn:
            self._duty_warn = warn
            if warn and not clipped:
                ctx.emit("inj_duty_high", value=duty, detail="aviso")

        cam_in = tables.get(_K.CAM_INTAKE_TARGET)
        cam_ex = tables.get(_K.CAM_EXHAUST_TARGET)
        vvt_in, vvt_ex = self.vvt.targets(
            ctx,
            cam_in.at(inputs) if cam_in is not None else 0.0,
            cam_ex.at(inputs) if cam_ex is not None else 0.0,
        )
        t = ctx.t
        commands = ActuatorCommands.model_construct(
            t_sim_s=t,
            injector_pw_ms=pw_out,
            injection_end_deg_btdc=None,
            ignition_advance_deg=adv_out,
            fuel_cut=list(fuel_cut),
            spark_cut=list(res.spark_cut),
            throttle_pct=ctx.pedal_pct,
            wastegate_duty_pct=duty_wg,
            vvt_intake_target_deg=vvt_in,
            vvt_exhaust_target_deg=vvt_ex,
            bypass_open=self._bypass_open(ctx, sensors.boost_pre_throttle_kpa),
            antilag_air_pct=res.antilag_air_pct,
            fuel_pump_duty_pct=100.0,
        )
        active = list(res.active)
        if self.closed_loop.active:
            active.append("closed_loop")
        if self.knock.any_retard:
            active.append("knock_control")
        if self.boost.pid_active:
            active.append("boost_control")
        if self.vvt.cfg.enabled:
            active.append("vvt")
        cl = self.closed_loop
        status = EcuStatus.model_construct(
            t_sim_s=t,
            lambda_target=lam,
            stft_pct=cl.stft * 100.0,
            ltft_pct=cl.ltft_value * 100.0,
            closed_loop_active=cl.active,
            fuel_mass_mg=mass_out,
            injector_pw_ms=list(pw_out),
            inj_duty_pct=duty,
            ignition_advance_deg=list(adv_out),
            knock_retard_deg=list(self.knock.retard),
            boost_target_kpa=final_target,
            wastegate_duty_pct=duty_wg,
            limiter_state=self.rev_limiter.state,
            active_strategies=active,
            arbitration_winner=res.winner,
            failsafe_actions=list(self.failsafe.active_actions),
            load_pct=load,
            torque_request_nm=torque_req,
            calibration_hash=cal.content_hash,
        )
        ctx.lambda_target_prev = lam
        ctx.fuel_cut_prev = any(fuel_cut)
        self.last_lambda_target = lam
        events: list[EcuEvent] = ctx.events
        return EcuStepResult(commands=commands, status=status, events=events)
