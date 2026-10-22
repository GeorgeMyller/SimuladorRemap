"""``ProfiledEcu``: adaptador de hardware entre a ECU e a física (profiles RF-20, RF-22 a RF-29).

Passo 2 do laço (simulation-bus 3.3)::

    sensor_view = adapter.transform_sensors(sensors)   # escalas declaradas
    result = runtime.step(sensor_view, dt)             # hooks do perfil
    commands = adapter.transform_commands(...)         # PMS, ordem, sincronismo, bico

A ECU calcula com a ``BaseSetup`` declarada; a física usa o hardware real. O
``EcuStatus`` guarda os valores comandados; o ``ActuatorCommands`` entregue à física leva
os valores reais:

- MAP lido pela escala declarada (S-05), IAT/ECT pela curva NTC declarada (S-09),
  lambda pela escala declarada da wideband (S-10; sem wideband declarada a leitura é
  inválida e a malha fechada fica indisponível, EC-11);
- avanço real = comandado + (PMS real − PMS configurado) (S-01); erro > 30° corta a
  faísca (S-04, EC-07); trava de ponto ``timing_lock_deg`` fixa o avanço comandado e o
  canal ``timing_light_deg`` mostra o avanço real lido pela lâmpada;
- roda fônica diferente, sequencial sem sensor de fase real ou borda de fase a 360° ⇒
  sem sincronismo ou falha de ignição em todos os cilindros (S-02, EC-08, EC-09);
- ordem de ignição divergente ⇒ ``spark_cut`` com injeção ativa nesses cilindros (S-03);
- bico real diferente do instalado no catálogo (``HardwareOverride``): a parte útil do
  pulso é escalada por ``Q_real / Q_catálogo`` para a física entregar a massa do bico
  real; vazão e dead time declarados entram no ``EcuHardwareConfig`` do runtime (S-06,
  S-08); AFR e densidade declarados também (S-07);
- ``m1-race``: modelo físico do bico (vazão vs ΔP, adição de pulso curto, RF-15);
- ``oem-stage``: borboleta pelo caminho de torque (PI sobre o MAP abaixo de baro − 5 kPa,
  wastegate a 0 %), eventos do hook (``oem_limp_mode``, ``oem_protection_disabled``);
- ``awaiting_base_setup``: cortes totais de faísca e injeção (RF-20).

Sem Pydantic validado no hot path: ``model_construct`` e listas pré-calculadas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isnan, nan
from typing import TYPE_CHECKING, Any, Final, cast

from simremap.ecu.calibration import CalibrationContent
from simremap.ecu.compiled import EcuHardwareConfig, compile_calibration
from simremap.ecu.contracts import EcuStatus, EcuStepResult
from simremap.ecu.runtime import EcuRuntime
from simremap.ecu.tables import interp1
from simremap.physics.contracts import ActuatorCommands, SensorReadings
from simremap.profiles.contracts import (
    BaseSetup,
    EcuProfileId,
    EcuState,
    HardwareOverride,
    ProfileEvent,
    ProfileStatus,
)
from simremap.profiles.hardware import (
    RealHardware,
    default_vehicle_hardware,
    load_vehicle_hardware,
    map_read_kpa,
    ntc_read_c,
    real_dead_time_row,
    real_hardware,
    wideband_read,
)
from simremap.profiles.hooks.common import DescriptorHooks
from simremap.profiles.hooks.oem_stage import OemStageHooks
from simremap.profiles.hooks.standalone import InjectorModel
from simremap.profiles.registry import ProfileRegistry, get_registry
from simremap.profiles.setup import build_checklist, hardware_config, oem_base_setup

if TYPE_CHECKING:
    from simremap.catalog.contracts import FuelSpec, VehicleSpec

__all__ = [
    "FUEL_MISMATCH_CONFIRM_S",
    "TDC_ERROR_MAX_DEG",
    "HardwareAdapter",
    "ProfiledEcu",
    "ProfiledEcuStepResult",
    "build_profiled_ecu",
]

TDC_ERROR_MAX_DEG: Final = 30.0  # ° (RF-23, EC-07)
FUEL_MISMATCH_CONFIRM_S: Final = 3.0  # s de STFT no limite (RF-26)
STFT_LIMIT_MARGIN_PCT: Final = 0.5  # % de folga para considerar o trim saturado
_ADV_MIN: Final = -30.0  # ° (limites de ActuatorCommands)
_ADV_MAX: Final = 60.0
_ZERO_HASH: Final = "0" * 64


def _wrap180(deg: float) -> float:
    """Ângulo em (−180, 180]."""
    d = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d  # noqa: PLR2004


@dataclass(slots=True, kw_only=True)
class ProfiledEcuStepResult(EcuStepResult):
    """``EcuStepResult`` + ``ProfileStatus`` e ``ProfileEvent`` do tick (D-BUS-09)."""

    profile_status: ProfileStatus
    profile_events: list[ProfileEvent] = field(default_factory=list)


class HardwareAdapter:
    """Transformações declarado × real (imutável por instalação do ``ProfiledEcu``)."""

    __slots__ = (
        "cut_reason",
        "declared",
        "ecu_state",
        "flow_scale",
        "identity_sensors",
        "injector_model",
        "lambda_cfg",
        "lambda_identity",
        "lambda_real",
        "map_cfg",
        "map_identity",
        "map_real",
        "misfire_cylinders",
        "n_cyl",
        "ntc",
        "profile_id",
        "real",
        "real_dead_ms",
        "real_dead_v",
        "spark_cut_all",
        "sync_detail",
        "sync_ok",
        "tdc_error_deg",
        "timing_lock_deg",
    )

    def __init__(
        self,
        *,
        profile_id: str,
        ecu_state: EcuState,
        declared: BaseSetup,
        real: RealHardware,
        n_cyl: int,
        real_dead_time: tuple[list[float], list[float]] | None = None,
    ) -> None:
        self.profile_id = profile_id
        self.ecu_state = ecu_state
        self.declared = declared
        self.real = real
        self.n_cyl = n_cyl
        trig = declared.trigger
        sensors = declared.sensors

        # Sincronismo (S-02, EC-08) e borda de fase (EC-09).
        self.sync_ok = True
        self.sync_detail = ""
        self.spark_cut_all = False
        self.cut_reason = ""
        if trig is None:
            self.sync_ok, self.sync_detail = False, "trigger_missing"
        elif trig.wheel != real.trigger_wheel:
            self.sync_ok, self.sync_detail = False, f"wheel {trig.wheel} != {real.trigger_wheel}"
        elif trig.phase_sensor != "none" and not real.phase_sensor_present:
            self.sync_ok, self.sync_detail = False, "phase_signal_missing"
        self.tdc_error_deg = 0.0
        if trig is not None:
            self.tdc_error_deg = _wrap180(real.tdc_offset_deg - trig.tdc_offset_deg)
            phase_err = (trig.phase_edge_deg - real.phase_edge_deg) % 720.0
            if trig.ignition_mode == "sequential" and 180.0 < phase_err < 540.0:  # noqa: PLR2004
                self.spark_cut_all, self.cut_reason = True, "phase_edge_360"
            if abs(self.tdc_error_deg) > TDC_ERROR_MAX_DEG:
                self.spark_cut_all, self.cut_reason = True, "tdc_offset_out_of_range"
        self.timing_lock_deg = trig.timing_lock_deg if trig is not None else None

        # Ordem de ignição divergente (S-03).
        misfire: list[int] = []
        if trig is not None and len(trig.firing_order) == len(real.firing_order):
            pos_cfg = {c: i for i, c in enumerate(trig.firing_order)}
            pos_real = {c: i for i, c in enumerate(real.firing_order)}
            misfire = sorted(c for c in pos_real if pos_cfg.get(c) != pos_real[c])
        self.misfire_cylinders = tuple(c - 1 for c in misfire if 1 <= c <= n_cyl)

        # Sensores (S-05, S-09, S-10).
        self.map_real = real.map_sensor_kpa
        self.map_cfg = (
            (sensors.map.min_kpa, sensors.map.max_kpa)
            if sensors.map is not None
            else real.map_sensor_kpa
        )
        self.map_identity = self.map_cfg == self.map_real
        self.ntc = (real.iat_curve, sensors.iat.curve, real.ect_curve, sensors.ect.curve)
        self.lambda_real = real.wideband
        wb = sensors.wideband
        self.lambda_cfg: tuple[float, float] | None = (
            (wb.lambda_at_0v, wb.lambda_at_5v) if wb is not None else None
        )
        self.lambda_identity = self.lambda_cfg == self.lambda_real
        self.identity_sensors = (
            self.map_identity
            and real.iat_curve == sensors.iat.curve
            and real.ect_curve == sensors.ect.curve
            and self.lambda_identity
        )

        # Bicos: bico real ≠ bico do catálogo (override) e modelo do m1-race.
        self.flow_scale = real.injector_flow_cc_min / real.catalog_injector_flow_cc_min
        dead = real_dead_time or ([8.0, 16.0], [0.0, 0.0])
        self.real_dead_v, self.real_dead_ms = dead
        model = None
        if profile_id == EcuProfileId.M1_RACE and declared.injectors is not None:
            candidate = InjectorModel(declared.injectors)
            model = candidate if candidate.active else None
        self.injector_model = model

    @property
    def setup_ok(self) -> bool:
        return self.ecu_state != "awaiting_base_setup"

    def transform_sensors(self, s: SensorReadings) -> SensorReadings:
        """Leituras vistas pela ECU (devolve o próprio objeto se nada muda)."""
        if self.identity_sensors and s.map_kpa < self.map_real[1]:
            return s
        update: dict[str, Any] = {}
        if not self.map_identity or s.map_kpa >= self.map_real[1] or s.map_kpa <= self.map_real[0]:
            update["map_kpa"] = map_read_kpa(s.map_kpa, self.map_real, self.map_cfg)
        iat_r, iat_c, ect_r, ect_c = self.ntc
        if iat_r != iat_c:
            update["iat_c"] = ntc_read_c(s.iat_c, iat_r, iat_c)
        if ect_r != ect_c:
            update["ect_c"] = ntc_read_c(s.ect_c, ect_r, ect_c)
        if self.lambda_cfg is None:
            update["lambda_measured"] = nan
        elif not self.lambda_identity:
            update["lambda_measured"] = wideband_read(
                s.lambda_measured, self.lambda_real, self.lambda_cfg
            )
        if not update:
            return s
        return s.model_copy(update=update)


class ProfiledEcu:
    """ECU do perfil no laço: adaptador + ``EcuRuntime`` genérico (um por sessão)."""

    def __init__(
        self,
        runtime: EcuRuntime | None,
        adapter: HardwareAdapter,
        *,
        hooks: DescriptorHooks | None = None,
    ) -> None:
        self.runtime = runtime
        self.adapter = adapter
        self.n_cyl = adapter.n_cyl
        self.profile_id = EcuProfileId(adapter.profile_id)
        self.hooks = hooks if hooks is not None else (runtime.hooks if runtime else None)
        self.oem = self.hooks if isinstance(self.hooks, OemStageHooks) else None
        if self.oem is not None and runtime is not None:
            self.oem.attach_runtime(runtime)
        self._was_cut = False
        self._was_unsynced = False
        self._was_tdc_cut = False
        self._misfire_reported = False
        self._stft_since = -1.0
        self.fuel_mismatch_suspected = False
        self._duty_clipped = False

    @property
    def ecu_state(self) -> EcuState:
        return self.adapter.ecu_state

    # ------------------------------------------------------------------ resultado nulo

    def _idle_result(self, s: SensorReadings) -> EcuStepResult:
        n = self.n_cyl
        zeros = [0.0] * n
        commands = ActuatorCommands.model_construct(
            t_sim_s=s.t_sim_s,
            injector_pw_ms=list(zeros),
            injection_end_deg_btdc=None,
            ignition_advance_deg=list(zeros),
            fuel_cut=[True] * n,
            spark_cut=[True] * n,
            throttle_pct=s.pedal_pct,
            wastegate_duty_pct=0.0,
            vvt_intake_target_deg=0.0,
            vvt_exhaust_target_deg=0.0,
            bypass_open=False,
            antilag_air_pct=0.0,
            fuel_pump_duty_pct=0.0,
        )
        status = EcuStatus.model_construct(
            t_sim_s=s.t_sim_s,
            lambda_target=1.0,
            stft_pct=0.0,
            ltft_pct=0.0,
            closed_loop_active=False,
            fuel_mass_mg=list(zeros),
            injector_pw_ms=list(zeros),
            inj_duty_pct=0.0,
            ignition_advance_deg=list(zeros),
            knock_retard_deg=list(zeros),
            boost_target_kpa=s.baro_kpa,
            wastegate_duty_pct=0.0,
            limiter_state="off",
            active_strategies=[],
            arbitration_winner="normal",
            failsafe_actions=[],
            load_pct=0.0,
            torque_request_nm=None,
            calibration_hash=_ZERO_HASH,
        )
        return EcuStepResult(commands=commands, status=status, events=[])

    # ------------------------------------------------------------------ step

    def step(  # noqa: PLR0912, PLR0915 - passo 2 do laço desenrolado (RNF-01)
        self, sensors: SensorReadings, dt: float
    ) -> ProfiledEcuStepResult:
        ad = self.adapter
        view = ad.transform_sensors(sensors)
        runtime = self.runtime
        result = runtime.step(view, dt) if runtime is not None else self._idle_result(view)
        cmds = result.commands
        status = result.status
        n = self.n_cyl
        t = sensors.t_sim_s
        pevents: list[ProfileEvent] = []

        lock = ad.timing_lock_deg
        cmd_adv = [lock] * n if lock is not None else list(cmds.ignition_advance_deg)
        err = ad.tdc_error_deg
        real_adv = [0.0] * n
        for k in range(n):
            a = cmd_adv[k] + err
            real_adv[k] = _ADV_MIN if a < _ADV_MIN else (_ADV_MAX if a > _ADV_MAX else a)
        fuel_cut = list(cmds.fuel_cut)
        spark_cut = list(cmds.spark_cut)
        pw = list(cmds.injector_pw_ms)

        cut_all = not ad.setup_ok or runtime is None
        if cut_all != self._was_cut:
            self._was_cut = cut_all
            if cut_all:
                pevents.append(_event(t, "no_start_setup_incomplete", detail=self.ecu_state))
        unsynced = not cut_all and not ad.sync_ok
        if unsynced != self._was_unsynced:
            self._was_unsynced = unsynced
            pevents.append(
                _event(
                    t,
                    "trigger_sync_lost" if unsynced else "trigger_sync_ok",
                    detail=ad.sync_detail,
                )
            )
        tdc_cut = not cut_all and ad.sync_ok and ad.cut_reason == "tdc_offset_out_of_range"
        if tdc_cut and not self._was_tdc_cut:
            pevents.append(_event(t, "tdc_offset_out_of_range", value=err))
        self._was_tdc_cut = tdc_cut
        if cut_all or unsynced:
            for k in range(n):
                fuel_cut[k] = True
                spark_cut[k] = True
                pw[k] = 0.0
        elif ad.spark_cut_all:
            for k in range(n):
                spark_cut[k] = True
        elif ad.misfire_cylinders:
            for k in ad.misfire_cylinders:
                spark_cut[k] = True
            if not self._misfire_reported and sensors.rpm > 0.0:
                self._misfire_reported = True
                for k in ad.misfire_cylinders:
                    pevents.append(_event(t, "firing_order_misfire", cylinder=k + 1))

        # Bicos: bico real (override) e modelo do m1-race.
        scale = ad.flow_scale
        model = ad.injector_model
        if (scale != 1.0 or model is not None) and not cut_all:
            dead_real = interp1(ad.real_dead_v, ad.real_dead_ms, view.battery_v)
            dp = view.fuel_pressure_kpa
            for k in range(n):
                p = pw[k]
                if p <= 0.0 or fuel_cut[k]:
                    continue
                if model is not None:
                    p = model.adjust(p, dead_real, dp)
                if scale != 1.0 and p > dead_real:
                    p = dead_real + (p - dead_real) * scale
                pw[k] = p if p < 50.0 else 50.0  # noqa: PLR2004 - limite de ActuatorCommands

        throttle = cmds.throttle_pct
        wastegate = cmds.wastegate_duty_pct
        oem = self.oem
        if oem is not None and runtime is not None:
            throttle = oem.throttle(view.map_kpa, view.baro_kpa, view.pedal_pct, dt)
            if oem.state.throttle_pi:
                wastegate = 0.0
            for kind, detail in oem.drain_events():
                pevents.append(_event(t, kind, detail=detail))

        # Diagnósticos de mistura e de bico (RF-26, EC-10).
        if runtime is not None and status.closed_loop_active:
            limit_pct = runtime.closed_loop.limit * 100.0
            if abs(status.stft_pct) >= limit_pct - STFT_LIMIT_MARGIN_PCT:
                if self._stft_since < 0.0:
                    self._stft_since = t
                confirmed = t - self._stft_since >= FUEL_MISMATCH_CONFIRM_S - 1e-9
                if confirmed and not self.fuel_mismatch_suspected:
                    self.fuel_mismatch_suspected = True
                    pevents.append(_event(t, "fuel_mismatch_suspected", value=status.stft_pct))
            else:
                self._stft_since = -1.0
        clipped = status.inj_duty_pct >= 100.0  # noqa: PLR2004
        if clipped != self._duty_clipped:
            self._duty_clipped = clipped
            if clipped:
                pevents.append(_event(t, "injector_undersized", value=status.inj_duty_pct))

        commands = ActuatorCommands.model_construct(
            t_sim_s=cmds.t_sim_s,
            injector_pw_ms=pw,
            injection_end_deg_btdc=cmds.injection_end_deg_btdc,
            ignition_advance_deg=real_adv,
            fuel_cut=fuel_cut,
            spark_cut=spark_cut,
            throttle_pct=throttle,
            wastegate_duty_pct=wastegate,
            vvt_intake_target_deg=cmds.vvt_intake_target_deg,
            vvt_exhaust_target_deg=cmds.vvt_exhaust_target_deg,
            bypass_open=cmds.bypass_open,
            antilag_air_pct=cmds.antilag_air_pct,
            fuel_pump_duty_pct=cmds.fuel_pump_duty_pct,
        )
        light = real_adv[0] if sensors.rpm > 0.0 and not spark_cut[0] else None
        lam_read = view.lambda_measured
        profile_status = self._status(t, ad, cmd_adv, err, light, view.map_kpa, lam_read)
        return ProfiledEcuStepResult(
            commands=commands,
            status=status,
            events=result.events,
            profile_status=profile_status,
            profile_events=pevents,
        )

    def _status(  # noqa: PLR0917 - campos do ProfileStatus
        self,
        t: float,
        ad: HardwareAdapter,
        cmd_adv: list[float],
        err: float,
        light: float | None,
        map_read: float,
        lam_read: float,
    ) -> ProfileStatus:
        oem = self.oem
        lam = None if isnan(lam_read) else lam_read  # NaN = sem wideband
        if oem is None:
            return ProfileStatus.model_construct(
                t_sim_s=t,
                profile_id=self.profile_id,
                ecu_state=ad.ecu_state,
                sync_ok=ad.sync_ok,
                ign_cmd_deg=cmd_adv,
                ign_real_minus_cmd_deg=err,
                timing_light_deg=light,
                map_read_kpa=map_read,
                lambda_read=lam,
                oem_torque_request_nm=None,
                oem_torque_desired_ind_nm=None,
                oem_torque_limiter_active=None,
                oem_load_target_pct=None,
                oem_load_actual_pct=None,
                oem_pressure_target_kpa=None,
                oem_torque_ign_retard_deg=None,
                oem_limp_mode=None,
            )
        st = oem.state
        return ProfileStatus.model_construct(
            t_sim_s=t,
            profile_id=self.profile_id,
            ecu_state=ad.ecu_state,
            sync_ok=ad.sync_ok,
            ign_cmd_deg=cmd_adv,
            ign_real_minus_cmd_deg=err,
            timing_light_deg=light,
            map_read_kpa=map_read,
            lambda_read=lam,
            oem_torque_request_nm=st.torque_request_nm,
            oem_torque_desired_ind_nm=st.torque_desired_ind_nm,
            oem_torque_limiter_active=st.limiter,
            oem_load_target_pct=st.load_target_pct,
            oem_load_actual_pct=st.load_actual_pct,
            oem_pressure_target_kpa=st.pressure_target_kpa,
            oem_torque_ign_retard_deg=st.ign_retard_deg,
            oem_limp_mode=st.limp,
        )

    def checklist_flags(self) -> dict[str, bool]:
        """Sinais do laço para o checklist (``FUEL_MISMATCH_SUSPECTED``)."""
        return {"fuel_mismatch_suspected": self.fuel_mismatch_suspected}


def _event(
    t: float,
    kind: str,
    *,
    cylinder: int | None = None,
    value: float | None = None,
    detail: str = "",
) -> ProfileEvent:
    return ProfileEvent.model_construct(
        t_sim_s=t, kind=cast("Any", kind), cylinder=cylinder, value=value, detail=detail[:200]
    )


# --------------------------------------------------------------------------- montagem


def build_profiled_ecu(
    *,
    vehicle: VehicleSpec,
    stock_fuel: FuelSpec,
    profile_id: str,
    ecu_state: EcuState,
    base_setup: BaseSetup | None,
    calibration: CalibrationContent | None,
    calibration_id: str = "uncompiled",
    calibration_version: int = 1,
    content_hash: str | None = None,
    override: HardwareOverride | None = None,
    enabled_strategies: frozenset[str] | None = None,
    registry: ProfileRegistry | None = None,
) -> ProfiledEcu:
    """Monta o ``ProfiledEcu`` de uma sessão (dyno-bench ``assembly``, comando ``ecu.swap``).

    ``oem-stage``: base fixa de série e ``EcuHardwareConfig`` do catálogo. Standalone: base
    declarada; sem setup mínimo, sem calibração ou em ``awaiting_base_setup`` o runtime fica
    ``None`` e o adaptador corta tudo.
    """
    reg = registry or get_registry()
    hw_file = load_vehicle_hardware(vehicle.vehicle_id) or default_vehicle_hardware(vehicle)
    real = real_hardware(hw_file, vehicle, override)
    oem = reg.family(profile_id) == "oem"
    n_cyl = vehicle.engine.n_cyl
    declared: BaseSetup
    cfg: EcuHardwareConfig | None
    if oem:
        declared = oem_base_setup(vehicle, hw_file, stock_fuel)
        cfg = EcuHardwareConfig.from_vehicle(vehicle, stock_fuel)
    else:
        declared = base_setup or BaseSetup()
        minimum = build_checklist(declared, hw_file, n_cyl=n_cyl).minimum_valid
        cfg = hardware_config(declared, vehicle) if minimum else None
        if cfg is None:
            ecu_state = "awaiting_base_setup"
    adapter = HardwareAdapter(
        profile_id=profile_id,
        ecu_state=ecu_state,
        declared=declared,
        real=real,
        n_cyl=n_cyl,
        real_dead_time=real_dead_time_row(vehicle),
    )
    hooks = reg.runtime_hooks(
        profile_id,
        vehicle.engine.displacement_cc / n_cyl * 1e-6,
        throttle_above_baro=vehicle.induction == "supercharger",
    )
    runtime: EcuRuntime | None = None
    if calibration is not None and cfg is not None and ecu_state != "awaiting_base_setup":
        compiled = compile_calibration(
            calibration,
            n_cyl,
            calibration_id=calibration_id,
            version=calibration_version,
            content_hash=content_hash,
        )
        runtime = EcuRuntime(compiled, hooks, cfg, enabled_strategies=enabled_strategies)
    return ProfiledEcu(runtime, adapter, hooks=hooks)
