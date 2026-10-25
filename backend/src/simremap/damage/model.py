"""``DamageModel``: knock, pré-ignição, saúde, falhas e bloqueio do motor no laço.

Contrato: ``contracts/simulation-bus.md`` 3.4; spec seção 8 ("Ordem interna de ``step()``"):

1. validar ``dt == 1 / sim_hz`` (1e-12 s) e as listas por cilindro;
2. motor bloqueado ⇒ estado congelado, sem sorteios nem eventos (EC-05);
3. por ``CombustionEvent`` (ordem ``t_sim_s``, cilindro): knock (RF-01 a RF-04),
   pré-ignição/LSPI (RF-07 a RF-09), sinal (RF-05), dano por ciclo (RF-11, RF-14, RF-15,
   RF-17);
4. grandezas contínuas por ``dt``: temperatura efetiva do pistão, Larson-Miller,
   lambda pobre, bronzinas e turbina (RF-12, RF-13, RF-15, RF-16);
5. clamp de ``health``, mapeamento de falhas (RF-18), bloqueio no mesmo tick (RF-19),
   escrita no buffer (RF-22).

A pré-ignição é avaliada antes do sinal do mesmo ciclo para que o sinal reflita o
mega-knock; como cada sorteio usa o seu próprio substream, a ordem não altera nenhuma
sequência de números.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import numpy as np

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.damage import native_bridge
from simremap.damage.config import DamageConfig
from simremap.damage.contracts import (
    INTACT_THRESHOLD,
    ComponentHealth,
    DamageState,
    EngineHealth,
    FailureEvent,
    FailureMechanism,
    FailureMode,
    KnockClass,
    KnockObservation,
    KnockSignal,
)
from simremap.damage.digest import DamageStreams, canonical_digest, damage_streams
from simremap.damage.errors import DamageError
from simremap.damage.failure import (
    CAUSES,
    ComponentSpec,
    build_components,
    build_failure_event,
    classify_failure,
    classify_warning,
)
from simremap.damage.knock import (
    KnockResult,
    evaluate_knock,
    fuel_energy_j,
    knock_piston_damage,
    knock_temp_step,
    octane_number,
    validate_event,
)
from simremap.damage.mechanical import (
    StructuralLimits,
    bearing_overrev_rate,
    draw_rod_weights,
    peak_pressure_damage,
    rod_damage,
    rod_load_ratio,
    turbo_overspeed,
    valve_overrev,
)
from simremap.damage.preignition import (
    PreignitionState,
    hot_spot_probability,
    lspi_probability,
    mega_knock_intensity,
    preignition_pressure_kpa,
)
from simremap.damage.signal import KnockSignalGenerator, in_sensor_window
from simremap.damage.spectrum import KnockSpectrumFrame, SpectrumGenerator
from simremap.damage.thermal import creep_damage, lean_delta_c, metal_temp_step
from simremap.damage.trace import (
    KNOCK_CLASS_CODE,
    PREIGNITION_CODE,
    DamageTraceSnapshot,
    TraceBuffer,
    TraceMeta,
)
from simremap.ecu.contracts import EcuStatus
from simremap.physics.contracts import CombustionEvent, EngineState

__all__ = ["SNAPSHOT_MAGIC", "DamageModel", "KnockEventRecord", "PhysicsLock"]

DT_TOLERANCE_S: Final = 1e-12
MAX_SIM_HZ: Final = 100_000
SNAPSHOT_MAGIC: Final = b"SRDMG1\n"
NO_SAMPLE_C: Final = -1000.0  # marcador de temperatura de metal sem amostra no snapshot
_CAUSE_INDEX: Final = {cause: i for i, cause in enumerate(CAUSES)}
_KNOCK_V_OFFSET: Final = 0.05  # V (A.10 da física)
_KNOCK_V_GAIN: Final = 1.5  # V por bar
_KNOCK_V_MAX: Final = 5.0  # V


class PhysicsLock(Protocol):
    """Parte do ``PhysicsEngine`` usada pelo dano (RF-19)."""

    def lock(self, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class KnockEventRecord:
    """Ciclo com classe ≥ ``light`` liberado pelo limitador de 10 eventos/s (RF-28)."""

    run_id: str | None
    t_sim_s: float
    cylinder: int
    knock_class: KnockClass
    intensity_raw: float  # bar de MAPO
    signal_raw: float  # KnockSignal do cilindro (bar)
    mapo_kpa: float
    theta_onset_deg_atdc: float | None
    rpm: float
    p_max_bar: float
    retard_deg: float
    simulated_only: bool

    def payload(
        self, intensity: float | None = None, threshold: float | None = None
    ) -> dict[str, Any]:
        """Payload de ``event.knock`` (D-WS-02); ``intensity`` normalizada 0–1."""
        if intensity is None:
            volts = min(_KNOCK_V_MAX, _KNOCK_V_OFFSET + _KNOCK_V_GAIN * self.signal_raw)
            intensity = min(
                1.0, max(0.0, (volts - _KNOCK_V_OFFSET) / (_KNOCK_V_MAX - _KNOCK_V_OFFSET))
            )
        return {
            "run_id": self.run_id,
            "cylinder": self.cylinder,
            "knock_class": self.knock_class.value,
            "intensity": intensity,
            "intensity_raw": self.intensity_raw,
            "mapo_kpa": self.mapo_kpa,
            "theta_onset_deg_atdc": self.theta_onset_deg_atdc,
            "retard_deg": self.retard_deg,
            "rpm": self.rpm,
            "p_max_bar": self.p_max_bar,
            "threshold": threshold,
            "simulated_only": self.simulated_only,
        }


@dataclass(slots=True)
class _ForcedFailure:
    mode: FailureMode
    mechanism: FailureMechanism


class DamageModel:
    """Modelo de dano de uma sessão (vive no worker do laço)."""

    def __init__(  # noqa: PLR0915
        self,
        config: DamageConfig,
        vehicle: VehicleSpec,
        fuel: FuelSpec,
        seed: int,
        damage_enabled: bool = True,
        *,
        session_id: str = "local",
        sim_hz: int = 1000,
        physics: PhysicsLock | None = None,
        ethanol_pct: float | None = None,
    ) -> None:
        if not damage_enabled and not config.enabled("damage_off"):
            raise DamageError(
                "damage_enabled = false exige a capacidade 'damage_off' em DamageConfig.features",
                code="DAMAGE_CONFIG_INVALID",
            )
        if not 1 <= sim_hz <= MAX_SIM_HZ:
            raise DamageError(f"sim_hz inválido: {sim_hz}", code="DAMAGE_CONFIG_INVALID")
        self._config = config
        self._vehicle = vehicle
        self._fuel = fuel
        self._ethanol_pct = ethanol_pct  # teor do blend flex (None nos outros combustíveis)
        self._seed = int(seed)
        self._enabled = damage_enabled
        self._session_id = session_id
        self._sim_hz = sim_hz
        self._dt = 1.0 / sim_hz
        self._physics = physics
        self._limits = StructuralLimits.from_vehicle(vehicle)
        self._n_cyl = self._limits.n_cyl
        self._specs = build_components(self._n_cyl, self._limits.has_turbo)
        self._index = {spec.component_id: i for i, spec in enumerate(self._specs)}
        self._streams: DamageStreams = damage_streams(self._seed)
        self._rod_weights = draw_rod_weights(self._streams.rod_weights, self._n_cyl, config)
        self._signal = KnockSignalGenerator(self._n_cyl, config, self._streams.knock_noise)
        self._spectrum = SpectrumGenerator(self._limits.bore_mm, config, self._streams.spectrum)
        self._pre = PreignitionState(
            self._n_cyl, config, self._streams.preignition, self._streams.lspi
        )
        self._trace = TraceBuffer(self._trace_meta())
        n_comp = len(self._specs)
        self._health = np.ones(n_comp)
        self._virtual = np.ones(n_comp)
        self._causes = np.zeros((n_comp, len(CAUSES)))
        self._first_damage = np.full(n_comp, np.nan)
        self._failed = np.zeros(n_comp, dtype=bool)
        self._warned = np.zeros(n_comp, dtype=bool)
        self._knock_temp = np.zeros(self._n_cyl)
        self._last_intensity = np.zeros(self._n_cyl)
        self._last_rod_ratio = np.zeros(self._n_cyl)
        self._last_knock_event_t: list[float | None] = [None] * self._n_cyl
        self._last_preignition: list[str | None] = [None] * self._n_cyl
        self._knock_last: list[KnockObservation | None] = [None] * self._n_cyl
        self._piston_eff = [0.0] * self._n_cyl
        # temperaturas de metal (1ª ordem; NaN = sem amostra: a 1ª amostra inicializa)
        self._valve_temp = np.full(self._n_cyl, np.nan)
        self._turbine_temp = np.full(1, np.nan)
        self._gasket_rings = np.zeros(self._n_cyl)  # dano por pressão por anel de fogo
        self._forced: dict[int, _ForcedFailure] = {}
        self._locked = False
        self._lock_reason: str | None = None
        self._tick = 0
        self._t = 0.0
        self._rpm = 0.0
        self._restore_count = 0
        self._sequence = 0
        self._run_id: str | None = None
        self._failures: list[FailureEvent] = []
        self._knock_events: list[KnockEventRecord] = []
        self._frozen: DamageState | None = None
        self._last_state: EngineState | None = None
        self._last_ecu: EcuStatus | None = None
        # ComponentHealth por componente (frozen); None = reconstruir no próximo components()
        self._component_cache: list[ComponentHealth | None] = [None] * n_comp
        self._kernel: Any = None
        self._bind_native()

    def _bind_native(self) -> None:
        """Liga o kernel nativo do passo contínuo aos arrays atuais (T019; None = Python)."""
        kernels = native_bridge.KERNELS
        if kernels is None:
            self._kernel = None
            return
        cfg = self._config
        limits = self._limits
        self._kernel = kernels.DamageKernel(
            health=self._health,
            virtual_health=self._virtual,
            causes=self._causes,
            first_damage=self._first_damage,
            knock_temp=self._knock_temp,
            last_intensity=self._last_intensity,
            valve_temp=self._valve_temp,
            turbine_temp=self._turbine_temp,
            n_cyl=self._n_cyl,
            has_turbine="turbo:turbine" in self._index,
            enabled=self._enabled,
            thermal=cfg.enabled("thermal"),
            mechanical=cfg.enabled("mechanical"),
            knock_temp_gain_c=cfg.knock_temp_gain_c,
            knock_temp_tau_s=cfg.knock_temp_tau_s,
            lean_map_min_kpa=cfg.lean_map_min_kpa,
            k_lean_c=cfg.k_lean_c,
            lambda_lean_ref=cfg.lambda_lean_ref,
            lm_constant=cfg.lm_constant,
            piston_limit_c=limits.max_piston_temp_c,
            piston_t_ref_s=cfg.piston_t_ref_s,
            valve_limit_c=limits.egt_limit_c + cfg.valve_egt_margin_c,
            valve_t_ref_s=cfg.valve_t_ref_s,
            valve_tau_s=cfg.valve_thermal_tau_s,
            turbine_limit_c=limits.egt_limit_c,
            turbine_t_ref_s=cfg.turbine_t_ref_s,
            turbine_tau_s=cfg.turbine_thermal_tau_s,
            max_rpm=limits.max_rpm,
            bearing_overrev_rate=cfg.bearing_overrev_rate,
            turbo_max_rpm=limits.turbo_max_rpm,
            turbo_burst_ratio=cfg.turbo_burst_ratio,
            turbo_overspeed_rate=cfg.turbo_overspeed_rate,
        )

    @property
    def native_kernel(self) -> bool:
        """``True`` se o passo contínuo usa o kernel Rust."""
        return self._kernel is not None

    # ------------------------------------------------------------------ propriedades

    @property
    def config(self) -> DamageConfig:
        return self._config

    @property
    def limits(self) -> StructuralLimits:
        return self._limits

    @property
    def n_cyl(self) -> int:
        return self._n_cyl

    @property
    def damage_enabled(self) -> bool:
        return self._enabled

    @property
    def engine_locked(self) -> bool:
        return self._locked

    @property
    def restore_count(self) -> int:
        return self._restore_count

    @property
    def rod_weights(self) -> list[float]:
        return list(self._rod_weights)

    @property
    def component_ids(self) -> list[str]:
        return [spec.component_id for spec in self._specs]

    @property
    def failures(self) -> list[FailureEvent]:
        """Todos os ``FailureEvent`` da sessão (inclui avisos)."""
        return list(self._failures)

    @property
    def knock_events(self) -> list[KnockEventRecord]:
        """Eventos ``event.knock`` liberados no último ``step`` (≤ 10/s por cilindro)."""
        return list(self._knock_events)

    @property
    def hot_spot_threshold_c(self) -> float:
        return self._config.preignition_threshold_for(self._fuel.fuel_id, self._ethanol_pct)

    def set_run(self, run_id: str | None) -> None:
        """Associa os próximos ``FailureEvent`` a uma puxada (``None`` fora de puxada)."""
        self._run_id = run_id

    def attach_physics(self, physics: PhysicsLock | None) -> None:
        self._physics = physics

    # ------------------------------------------------------------------ laço

    def knock_signal(self) -> KnockSignal:
        """Sinal do último ciclo de cada cilindro (entrada de ``read_sensors``)."""
        if not self._config.enabled("signal"):
            return KnockSignal.silent(self._n_cyl)
        return self._signal.signal()

    def step(
        self, state: EngineState, dt: float, ecu_status: EcuStatus | None = None
    ) -> DamageState:
        """Avança o dano de um tick (``dt = 1 / sim_hz``)."""
        if abs(dt - self._dt) > DT_TOLERANCE_S:
            raise DamageError(
                f"dt {dt!r} difere de 1/sim_hz ({self._dt!r})", code="DAMAGE_DT_MISMATCH"
            )
        if state.n_cyl != self._n_cyl:
            raise DamageError(
                f"EngineState com {state.n_cyl} cilindros; o veículo tem {self._n_cyl}",
                code="DAMAGE_INPUT_INVALID",
            )
        if ecu_status is not None and len(ecu_status.knock_retard_deg) != self._n_cyl:
            raise DamageError(
                "EcuStatus.knock_retard_deg sem n_cyl valores", code="DAMAGE_INPUT_INVALID"
            )
        self._knock_events = []
        if self._locked and self._frozen is not None:
            self._tick, self._t = state.tick, state.t_sim_s
            return self._frozen.model_copy(
                update={"t_sim_s": state.t_sim_s, "tick": state.tick, "new_failures": []}
            )
        for event in state.events:
            validate_event(event)
        self._tick, self._t, self._rpm = state.tick, state.t_sim_s, state.rpm
        self._last_state, self._last_ecu = state, ecu_status
        self._forced = {}
        for event in sorted(state.events, key=lambda e: (e.t_sim_s, e.cylinder)):
            self._process_event(event, state, ecu_status)
        self._continuous(state, dt)
        new_failures = self._map_failures(state)
        catastrophic = [f for f in new_failures if f.catastrophic]
        if catastrophic and self._enabled and not self._locked:
            self._locked = True
            self._lock_reason = catastrophic[0].mode.value
            if self._physics is not None:
                self._physics.lock(self._lock_reason)
        self._record_tick(state, ecu_status, force=bool(new_failures))
        result = self._build_state(new_failures)
        if self._locked:
            self._frozen = result
        return result

    # ------------------------------------------------------------------ eventos

    def _process_event(  # noqa: PLR0915
        self, event: CombustionEvent, state: EngineState, ecu: EcuStatus | None
    ) -> None:
        cfg = self._config
        c = event.cylinder
        i = c - 1
        fuel_ok = not event.misfire and event.lambda_real is not None
        q_disp = fuel_energy_j(
            state.m_fuel_mg[i],
            state.m_air_mg[i],
            self._fuel.afr_stoich,
            self._fuel.lhv_mj_kg,
            cfg.combustion_efficiency,
        )
        knock = (
            evaluate_knock(event, q_disp, cfg)
            if cfg.enabled("knock") and fuel_ok
            else KnockResult.silent()
        )
        preignition: Literal["none", "hot_spot", "lspi"] = "none"
        p_pi: float | None = None
        rod_force = event.rod_force_peak_n
        peak_pressure = event.p_max_kpa
        if cfg.enabled("preignition") and fuel_ok:
            p_hs = hot_spot_probability(
                state.hot_spot_temp_c[i],
                self.hot_spot_threshold_c,
                state.iat_c,
                state.map_kpa,
                cfg,
            )
            p_lspi = lspi_probability(
                self._limits.injection_type, event.rpm, event.imep_gross_kpa, state.iat_c, cfg
            )
            outcome = self._pre.evaluate(c, p_hs, p_lspi)
            if outcome is not None:
                preignition = outcome.kind
                p_pi = preignition_pressure_kpa(
                    event.p_max_kpa, outcome.theta_pi_btdc, state.ignition_advance_deg[i], cfg
                )
                intensity = mega_knock_intensity(p_pi, cfg)
                knock = KnockResult(
                    lw_integral_end=knock.lw_integral_end,
                    theta_onset_deg_atdc=event.theta_pmax_deg_atdc,
                    burned_fraction_onset=None,
                    autoignited_fraction=1.0,
                    mapo_kpa=intensity * 100.0,
                    intensity=intensity,
                    knock_energy_j=max(0.0, q_disp),
                    knock_class=KnockClass.SEVERE,
                )
                if event.p_max_kpa > 0.0:
                    rod_force = event.rod_force_peak_n * p_pi / event.p_max_kpa
                peak_pressure = p_pi
                self._last_preignition[i] = preignition
        signal_value = (
            self._signal.on_cycle(c, knock.intensity, knock.theta_onset_deg_atdc, event.rpm)
            if cfg.enabled("signal")
            else 0.0
        )
        if cfg.enabled("spectrum"):
            self._spectrum.observe(knock.intensity)
        t = event.t_sim_s
        if p_pi is not None:
            piston = self._index[f"piston:{c}"]
            p_lim = self._limits.cylinder_pressure_limit_kpa
            self._apply(piston, cfg.preignition_piston_damage * p_pi / p_lim, "preignition", t)
            if p_pi >= cfg.preignition_failure_ratio * p_lim:
                mechanism = (
                    FailureMechanism.LSPI
                    if preignition == "lspi"
                    else FailureMechanism.HOT_SPOT_PREIGNITION
                )
                self._force(piston, "preignition", FailureMode.PRE_IGNITION, mechanism, t)
        elif cfg.enabled("knock"):
            damage = knock_piston_damage(knock.intensity, knock.knock_energy_j, cfg)
            if damage > 0.0:
                self._apply(self._index[f"piston:{c}"], damage, "knock", t)
                self._apply(
                    self._index["head_gasket"], cfg.head_gasket_knock_share * damage, "knock", t
                )
        ratio = rod_load_ratio(state.torque_nm, rod_force, self._limits)
        self._last_rod_ratio[i] = ratio
        if cfg.enabled("mechanical"):
            self._mechanical_cycle(c, ratio, event.rpm, peak_pressure, t)
        self._last_intensity[i] = knock.intensity
        retard = 0.0 if ecu is None else float(ecu.knock_retard_deg[i])
        observation = KnockObservation.model_construct(
            cylinder=c,
            t_sim_s=t,
            rpm=event.rpm,
            lw_integral_end=knock.lw_integral_end,
            theta_onset_deg_atdc=knock.theta_onset_deg_atdc,
            burned_fraction_onset=knock.burned_fraction_onset,
            autoignited_fraction=knock.autoignited_fraction,
            mapo_kpa=knock.mapo_kpa,
            intensity=knock.intensity,
            knock_energy_j=knock.knock_energy_j,
            knock_class=knock.knock_class,
            in_sensor_window=in_sensor_window(knock.theta_onset_deg_atdc, cfg),
            preignition=preignition,
            p_preignition_kpa=p_pi,
        )
        self._knock_last[i] = observation
        self._trace.record_cycle(
            {
                "t_sim_s": t,
                "cylinder": float(c),
                "rpm": event.rpm,
                "map_kpa": state.map_kpa,
                "lw_integral_end": knock.lw_integral_end,
                "theta_onset_deg_atdc": knock.theta_onset_deg_atdc,
                "intensity": knock.intensity,
                "knock_class": KNOCK_CLASS_CODE[knock.knock_class.value],
                "preignition": PREIGNITION_CODE[preignition],
                "p_max_kpa": event.p_max_kpa,
                "p_preignition_kpa": p_pi,
                "rod_load_ratio": ratio,
                "ignition_advance_deg": state.ignition_advance_deg[i],
                "lambda": event.lambda_real,
                "hot_spot_temp_c": state.hot_spot_temp_c[i],
                "knock_retard_deg": None if ecu is None else retard,
                "t_unburned_max_k": event.t_unburned_max_k,
            }
        )
        if knock.knock_class != KnockClass.NONE:
            last = self._last_knock_event_t[i]
            if last is None or t - last >= cfg.knock_event_min_interval_s - 1e-9:
                self._last_knock_event_t[i] = t
                self._knock_events.append(
                    KnockEventRecord(
                        run_id=self._run_id,
                        t_sim_s=t,
                        cylinder=c,
                        knock_class=knock.knock_class,
                        intensity_raw=knock.intensity,
                        signal_raw=signal_value,
                        mapo_kpa=knock.mapo_kpa,
                        theta_onset_deg_atdc=knock.theta_onset_deg_atdc,
                        rpm=event.rpm,
                        p_max_bar=event.p_max_kpa / 100.0,
                        retard_deg=retard,
                        simulated_only=not self._enabled,
                    )
                )

    def _mechanical_cycle(
        self, cylinder: int, ratio: float, rpm: float, peak_pressure_kpa: float, t: float
    ) -> None:
        cfg = self._config
        rod = self._index[f"rod:{cylinder}"]
        damage, instant = rod_damage(ratio, self._rod_weights[cylinder - 1], cfg)
        if instant:
            self._force(
                rod, "overload", FailureMode.ROD_FAILURE, FailureMechanism.ROD_INSTANT_BEND, t
            )
        elif damage > 0.0:
            self._apply(rod, damage, "overload", t)
            self._apply(self._index["bearings"], cfg.bearing_rod_share * damage, "overload", t)
        valves = self._index[f"valves:{cylinder}"]
        damage, contact = valve_overrev(rpm, self._limits, cfg)
        if contact:
            self._force(
                valves,
                "overrev",
                FailureMode.PISTON_FAILURE,
                FailureMechanism.VALVE_PISTON_CONTACT,
                t,
            )
        elif damage > 0.0:
            self._apply(valves, damage, "overrev", t)
        pressure_damage = peak_pressure_damage(peak_pressure_kpa, self._limits, cfg)
        if pressure_damage > 0.0:
            # anel de fogo por cilindro: a junta rompe no anel mais carregado, por isso o
            # dano por pressão da junta é o máximo dos anéis e não a soma dos cilindros
            rings = self._gasket_rings
            before = float(rings.max())
            rings[cylinder - 1] += pressure_damage
            increment = float(rings.max()) - before
            if increment > 0.0:
                self._apply(self._index["head_gasket"], increment, "pressure", t)

    # ------------------------------------------------------------------ contínuo

    def _continuous(self, state: EngineState, dt: float) -> None:  # noqa: PLR0912
        if self._kernel is not None:
            self._continuous_native(state, dt)
            return
        cfg = self._config
        limits = self._limits
        t = state.t_sim_s
        thermal = cfg.enabled("thermal")
        for i in range(self._n_cyl):
            if thermal:
                self._knock_temp[i] = knock_temp_step(
                    float(self._knock_temp[i]), float(self._last_intensity[i]), dt, cfg
                )
                lean = lean_delta_c(state.lambda_cyl[i], state.map_kpa, cfg)
            else:
                lean = 0.0
            t_eff = state.piston_temp_c[i] + float(self._knock_temp[i]) + lean
            self._piston_eff[i] = t_eff
            if not thermal:
                continue
            piston_damage = creep_damage(
                t_eff, limits.max_piston_temp_c, cfg.piston_t_ref_s, dt, cfg
            )
            if piston_damage > 0.0:
                self._apply(self._index[f"piston:{i + 1}"], piston_damage, "thermal", t)
            previous = float(self._valve_temp[i])
            if math.isnan(previous):  # 1.ª amostra: metal não acima do gás do coletor
                previous = min(state.egt_c[i], state.egt_collector_c)
            valve_t = metal_temp_step(previous, state.egt_c[i], dt, cfg.valve_thermal_tau_s)
            self._valve_temp[i] = valve_t
            valve_damage = creep_damage(
                valve_t,
                limits.egt_limit_c + cfg.valve_egt_margin_c,
                cfg.valve_t_ref_s,
                dt,
                cfg,
            )
            if valve_damage > 0.0:
                self._apply(self._index[f"valves:{i + 1}"], valve_damage, "thermal", t)
        turbine = self._index.get("turbo:turbine")
        if thermal and turbine is not None:
            turbine_t = metal_temp_step(
                float(self._turbine_temp[0]), state.egt_collector_c, dt, cfg.turbine_thermal_tau_s
            )
            self._turbine_temp[0] = turbine_t
            turbine_damage = creep_damage(
                turbine_t, limits.egt_limit_c, cfg.turbine_t_ref_s, dt, cfg
            )
            if turbine_damage > 0.0:
                self._apply(turbine, turbine_damage, "thermal", t)
        if not cfg.enabled("mechanical"):
            return
        bearing_rate = bearing_overrev_rate(state.rpm, limits, cfg)
        if bearing_rate > 0.0:
            self._apply(self._index["bearings"], bearing_rate * dt, "overrev", t)
        if turbine is not None:
            rate, burst = turbo_overspeed(state.turbo_rpm, limits, cfg)
            if burst:
                self._force(
                    turbine,
                    "overrev",
                    FailureMode.TURBO_MELTDOWN,
                    FailureMechanism.TURBO_OVERSPEED_BURST,
                    t,
                )
            elif rate > 0.0:
                self._apply(turbine, rate * dt, "overrev", t)

    def _continuous_native(self, state: EngineState, dt: float) -> None:
        """``_continuous`` no kernel Rust (mesma ordem; o ``_force`` do burst fica aqui)."""
        piston_eff, touched, burst = self._kernel.continuous(
            state.piston_temp_c,
            state.lambda_cyl,
            state.egt_c,
            state.map_kpa,
            state.egt_collector_c,
            state.rpm,
            state.turbo_rpm,
            state.t_sim_s,
            dt,
        )
        self._piston_eff = piston_eff
        cache = self._component_cache
        for index in touched:
            cache[index] = None
        if burst:
            self._force(
                self._index["turbo:turbine"],
                "overrev",
                FailureMode.TURBO_MELTDOWN,
                FailureMechanism.TURBO_OVERSPEED_BURST,
                state.t_sim_s,
            )

    # ------------------------------------------------------------------ saúde

    def _apply(self, index: int, amount: float, cause: str, t: float) -> None:
        if amount <= 0.0:
            return
        self._component_cache[index] = None
        if self._enabled:
            self._health[index] = max(0.0, float(self._health[index]) - amount)
        self._virtual[index] = max(0.0, float(self._virtual[index]) - amount)
        self._causes[index, _CAUSE_INDEX[cause]] += amount
        if math.isnan(self._first_damage[index]):
            self._first_damage[index] = t

    def _force(
        self,
        index: int,
        cause: str,
        mode: FailureMode,
        mechanism: FailureMechanism,
        t: float,
    ) -> None:
        current = float(self._health[index] if self._enabled else self._virtual[index])
        self._apply(index, max(current, 1e-12), cause, t)
        self._forced.setdefault(index, _ForcedFailure(mode, mechanism))

    def _causes_of(self, index: int) -> dict[str, float]:
        return {
            cause: float(self._causes[index, j])
            for j, cause in enumerate(CAUSES)
            if self._causes[index, j] > 0.0
        }

    def _map_failures(self, state: EngineState) -> list[FailureEvent]:
        """RF-18: falha (health 0) e aviso (health ≤ 0,50, 1.ª vez), em ordem canônica."""
        events: list[FailureEvent] = []
        threshold = self._config.warning_health_threshold
        for index, spec in enumerate(self._specs):
            value = float(self._health[index] if self._enabled else self._virtual[index])
            if self._failed[index]:
                continue
            if not (value <= 0.0 or (value <= threshold and not self._warned[index])):
                continue  # sem falha nem aviso novo: dispensa as causas
            causes = self._causes_of(index)
            pre_kind = self._last_preignition[spec.cylinder - 1] if spec.cylinder else None
            if value <= 0.0:
                forced = self._forced.get(index)
                if forced is not None:
                    mode, mechanism = forced.mode, forced.mechanism
                else:
                    mode, mechanism = classify_failure(spec.kind, causes, pre_kind)
                self._failed[index] = True
                self._warned[index] = True
                self._component_cache[index] = None
                events.append(self._event(spec, mode, mechanism, True, value, state))
            elif value <= threshold and not self._warned[index]:
                self._warned[index] = True
                mode, mechanism = classify_warning(spec.kind, causes, pre_kind)
                events.append(self._event(spec, mode, mechanism, False, value, state))
        self._failures.extend(events)
        return events

    def _event(
        self,
        spec: ComponentSpec,
        mode: FailureMode,
        mechanism: FailureMechanism,
        failure: bool,
        health_after: float,
        state: EngineState,
    ) -> FailureEvent:
        self._sequence += 1
        return build_failure_event(
            session_id=self._session_id,
            run_id=self._run_id,
            seed=self._seed,
            tick=state.tick,
            t_sim_s=state.t_sim_s,
            sequence=self._sequence,
            spec=spec,
            mode=mode,
            mechanism=mechanism,
            catastrophic=failure and self._enabled,
            simulated_only=not self._enabled,
            health_after=health_after,
            causal_variables=self._causal_variables(spec, state),
        )

    def _causal_variables(self, spec: ComponentSpec, state: EngineState) -> dict[str, float]:
        values: dict[str, float] = {
            "torque_nm": state.torque_nm,
            "map_kpa": state.map_kpa,
            "iat_c": state.iat_c,
            "egt_collector_c": state.egt_collector_c,
            "rpm": state.rpm,
        }
        if self._limits.turbo_max_rpm is not None and state.turbo_rpm is not None:
            values["turbo_rpm_ratio"] = state.turbo_rpm / self._limits.turbo_max_rpm
        if state.lambda_collector is not None:
            values["lambda"] = state.lambda_collector
        if spec.cylinder is not None:
            i = spec.cylinder - 1
            values["knock_signal_raw"] = self._signal.values[i]
            values["knock_intensity"] = float(self._last_intensity[i])
            values["piston_temp_eff_c"] = self._piston_eff[i]
            values["rod_load_ratio"] = float(self._last_rod_ratio[i])
            values["ignition_advance_deg"] = state.ignition_advance_deg[i]
            values["egt_c"] = state.egt_c[i]
            lam = state.lambda_cyl[i]
            if lam is not None:
                values["lambda"] = lam
            if self._last_ecu is not None:
                values["knock_retard_deg"] = float(self._last_ecu.knock_retard_deg[i])
        elif self._last_ecu is not None:
            values["knock_retard_deg"] = float(max(self._last_ecu.knock_retard_deg))
        return {k: float(v) for k, v in values.items() if math.isfinite(float(v))}

    # ------------------------------------------------------------------ saída

    def components(self) -> list[ComponentHealth]:
        """``ComponentHealth`` atuais em ordem canônica.

        Os modelos são ``frozen``: cada um é reconstruído só depois de ``_apply``, falha,
        ``restore`` ou ``load_snapshot`` do componente (o resto do tick reutiliza a cache).
        """
        cache = self._component_cache
        for index, cached in enumerate(cache):
            if cached is None:
                cache[index] = self._build_component(index)
        return list(cache)  # type: ignore[arg-type]

    def _build_component(self, index: int) -> ComponentHealth:
        spec = self._specs[index]
        first = float(self._first_damage[index])
        return ComponentHealth.model_construct(
            component_id=spec.component_id,
            kind=spec.kind,
            cylinder=spec.cylinder,
            health=float(self._health[index]),
            virtual_health=float(self._virtual[index]),
            damage_by_cause=self._causes_of(index),
            failed=bool(self._failed[index]) and self._enabled,
            first_damage_t_sim_s=None if math.isnan(first) else first,
        )

    def _invalidate_components(self) -> None:
        self._component_cache = [None] * len(self._specs)

    def _build_state(self, new_failures: list[FailureEvent]) -> DamageState:
        return DamageState.model_construct(
            t_sim_s=self._t,
            tick=self._tick,
            damage_enabled=self._enabled,
            engine_locked=self._locked,
            components=self.components(),
            knock_last=list(self._knock_last),
            knock_signal=self.knock_signal(),
            piston_temp_eff_c=list(self._piston_eff),
            new_failures=new_failures,
            damage_digest=None,
        )

    def _record_tick(self, state: EngineState, ecu: EcuStatus | None, *, force: bool) -> None:
        if not (force or self._trace.should_record_tick(state.t_sim_s)):
            return
        self._trace.record_tick(
            {
                "t_sim_s": state.t_sim_s,
                "tick": float(state.tick),
                "rpm": state.rpm,
                "map_kpa": state.map_kpa,
                "iat_c": state.iat_c,
                "torque_nm": state.torque_nm,
                "egt_collector_c": state.egt_collector_c,
                "turbo_rpm": state.turbo_rpm,
                "lambda_collector": state.lambda_collector,
                "boost_target_kpa": None if ecu is None else ecu.boost_target_kpa,
                "lambda_target": None if ecu is None else ecu.lambda_target,
            },
            {
                "knock_retard_deg": None if ecu is None else list(ecu.knock_retard_deg),
                "lambda_cyl": list(state.lambda_cyl),
                "piston_temp_eff_c": list(self._piston_eff),
                "hot_spot_temp_c": list(state.hot_spot_temp_c),
                "egt_c": list(state.egt_c),
                "ignition_advance_deg": list(state.ignition_advance_deg),
            },
            self._health if self._enabled else self._virtual,
        )

    def spectrum_frame(self, t_sim_s: float) -> KnockSpectrumFrame:
        """Espectro do frame (RF-06); usa só o substream ``spectrum``."""
        return self._spectrum.frame(t_sim_s, self._rpm)

    def freeze_trace(self) -> DamageTraceSnapshot:
        """Cópia imutável do buffer de 30 s (entrada do laudo)."""
        return self._trace.freeze(
            self.components(),
            self._failures,
            self._t,
            extra={"restore_count": float(self._restore_count)},
        )

    def engine_health(
        self, *, include_failures: bool = True, last_forensic_report_url: str | None = None
    ) -> EngineHealth:
        """``EngineHealth`` da sessão (E-12, E-13)."""
        return EngineHealth.build(
            session_id=self._session_id,
            vehicle_id=self._vehicle.vehicle_id,
            t_sim_s=self._t,
            damage_enabled=self._enabled,
            engine_locked=self._locked,
            components=[ComponentHealth.model_validate(c.model_dump()) for c in self.components()],
            failures=self.failures if include_failures else [],
            restore_count=self._restore_count,
            last_forensic_report_url=last_forensic_report_url,
        )

    @property
    def intact(self) -> bool:
        return float(self._health.min()) >= INTACT_THRESHOLD

    # ------------------------------------------------------------------ comandos

    def restore(self) -> None:
        """RF-21: repõe o motor de série (não ressemeia os geradores)."""
        self._health.fill(1.0)
        self._virtual.fill(1.0)
        self._causes.fill(0.0)
        self._first_damage.fill(np.nan)
        self._failed.fill(False)
        self._warned.fill(False)
        self._knock_temp.fill(0.0)
        self._last_intensity.fill(0.0)
        self._last_rod_ratio.fill(0.0)
        self._last_knock_event_t = [None] * self._n_cyl
        self._last_preignition = [None] * self._n_cyl
        self._knock_last = [None] * self._n_cyl
        self._piston_eff = [0.0] * self._n_cyl
        self._valve_temp.fill(np.nan)  # válvulas e turbina novas: reiniciam na 1ª amostra
        self._turbine_temp.fill(np.nan)
        self._gasket_rings.fill(0.0)
        self._signal.reset()
        self._spectrum.reset()
        self._pre.reset()
        self._trace.clear()
        self._locked = False
        self._lock_reason = None
        self._frozen = None
        self._rpm = 0.0
        self._restore_count += 1
        self._invalidate_components()

    def set_fuel(self, fuel: FuelSpec) -> None:
        """Troca o combustível (só com o motor parado, EC-16)."""
        if self._rpm > 0.0:
            raise DamageError(
                "Troca de combustível com o motor em funcionamento",
                code="DAMAGE_FUEL_CHANGE_WHILE_RUNNING",
            )
        self._fuel = fuel
        self._trace = TraceBuffer(self._trace_meta())

    def _trace_meta(self) -> TraceMeta:
        points = self._vehicle.reference_command_schedule.points
        return TraceMeta(
            session_id=self._session_id,
            vehicle_id=self._vehicle.vehicle_id,
            fuel_id=self._fuel.fuel_id,
            seed=self._seed,
            sim_hz=self._sim_hz,
            n_cyl=self._n_cyl,
            damage_enabled=self._enabled,
            component_ids=tuple(spec.component_id for spec in self._specs),
            limits=self._limits,
            hot_spot_threshold_c=self.hot_spot_threshold_c,
            stock_boost_kpa=max(p.map_target_kpa for p in points) if points else None,
            octane=octane_number(self._fuel.ron, self._fuel.mon),
            config=self._config,
        )

    # ------------------------------------------------------------------ determinismo

    def _scalar_state(self, include_spectrum: bool) -> dict[str, Any]:
        rng = self._streams.all_states() if include_spectrum else self._streams.digest_states()
        return {
            "version": self._config.config_version,
            "n_cyl": self._n_cyl,
            "component_ids": self.component_ids,
            "tick": self._tick,
            "t_sim_s": self._t,
            "rpm": self._rpm,
            "locked": self._locked,
            "lock_reason": self._lock_reason,
            "restore_count": self._restore_count,
            "sequence": self._sequence,
            "damage_enabled": self._enabled,
            "failed": [bool(v) for v in self._failed],
            "warned": [bool(v) for v in self._warned],
            "runaway": list(self._pre.runaway),
            "last_preignition": list(self._last_preignition),
            "last_knock_event_t": list(self._last_knock_event_t),
            "failure_ids": [f.failure_event_id for f in self._failures],
            "rng": rng,
        }

    def _array_state(self) -> dict[str, np.ndarray]:
        return {
            "health": self._health,
            "virtual": self._virtual,
            "causes": self._causes,
            "first_damage": np.nan_to_num(self._first_damage, nan=-1.0),
            "knock_temp": self._knock_temp,
            "last_intensity": self._last_intensity,
            "last_rod_ratio": self._last_rod_ratio,
            "signal": np.asarray(self._signal.values, dtype=np.float64),
            "rod_weights": np.asarray(self._rod_weights, dtype=np.float64),
            "piston_eff": np.asarray(self._piston_eff, dtype=np.float64),
            "valve_temp": np.nan_to_num(self._valve_temp, nan=NO_SAMPLE_C),
            "turbine_temp": np.nan_to_num(self._turbine_temp, nan=NO_SAMPLE_C),
            "gasket_rings": self._gasket_rings,
        }

    def damage_digest(self) -> str:
        """SHA-256 hex do estado canônico (sem o substream ``spectrum`` nem o buffer)."""
        return canonical_digest(self._scalar_state(include_spectrum=False), self._array_state())

    def snapshot(self) -> bytes:
        """Cabeçalho JSON canônico + float64 little-endian com SHA-256 (sem ``pickle``)."""
        arrays = self._array_state()
        payload = b"".join(
            np.ascontiguousarray(a, dtype="<f8").tobytes() for _, a in sorted(arrays.items())
        )
        header = {
            "state": self._scalar_state(include_spectrum=True),
            "arrays": {name: list(a.shape) for name, a in sorted(arrays.items())},
            "failures": [f.model_dump(mode="json") for f in self._failures],
            "knock_last": [
                None if o is None else o.model_dump(mode="json") for o in self._knock_last
            ],
            "run_id": self._run_id,
            "spectrum_i_max": self._spectrum.i_max,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        }
        raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return SNAPSHOT_MAGIC + struct.pack("<Q", len(raw)) + raw + payload

    def load_snapshot(self, blob: bytes) -> None:  # noqa: PLR0915
        """Repõe o estado de ``snapshot()``; ``DAMAGE_SNAPSHOT_INVALID`` se incoerente."""
        try:
            header, payload = self._parse_snapshot(blob)
            state = header["state"]
            if state["component_ids"] != self.component_ids or state["n_cyl"] != self._n_cyl:
                raise ValueError("snapshot de outro veículo")
            arrays: dict[str, np.ndarray] = {}
            offset = 0
            for name, shape in sorted(header["arrays"].items()):
                size = int(np.prod(shape)) if shape else 1
                chunk = payload[offset : offset + 8 * size]
                if len(chunk) != 8 * size:
                    raise ValueError("payload curto")
                arrays[name] = np.frombuffer(chunk, dtype="<f8").reshape(shape).copy()
                offset += 8 * size
            failures = [FailureEvent.model_validate(f) for f in header["failures"]]
            knock_last = [
                None if o is None else KnockObservation.model_validate(o)
                for o in header["knock_last"]
            ]
        except DamageError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise DamageError(
                f"Snapshot do dano inválido: {exc}", code="DAMAGE_SNAPSHOT_INVALID"
            ) from exc
        self._health = arrays["health"]
        self._virtual = arrays["virtual"]
        self._causes = arrays["causes"]
        first = arrays["first_damage"]
        self._first_damage = np.where(first < 0.0, np.nan, first)
        self._knock_temp = arrays["knock_temp"]
        self._last_intensity = arrays["last_intensity"]
        self._last_rod_ratio = arrays["last_rod_ratio"]
        self._signal.load(arrays["signal"].tolist())
        self._rod_weights = arrays["rod_weights"].tolist()
        self._piston_eff = arrays["piston_eff"].tolist()
        self._gasket_rings = arrays["gasket_rings"]
        for name in ("valve_temp", "turbine_temp"):
            values = arrays[name]
            setattr(self, f"_{name}", np.where(values <= NO_SAMPLE_C, np.nan, values))
        self._tick = int(state["tick"])
        self._t = float(state["t_sim_s"])
        self._rpm = float(state["rpm"])
        self._locked = bool(state["locked"])
        self._lock_reason = state["lock_reason"]
        self._restore_count = int(state["restore_count"])
        self._sequence = int(state["sequence"])
        self._failed = np.asarray(state["failed"], dtype=bool)
        self._warned = np.asarray(state["warned"], dtype=bool)
        self._pre.runaway = [int(v) for v in state["runaway"]]
        self._last_preignition = list(state["last_preignition"])
        self._last_knock_event_t = list(state["last_knock_event_t"])
        self._streams.load_states(state["rng"])
        self._failures = failures
        self._knock_last = knock_last
        self._run_id = header["run_id"]
        self._spectrum.reset()
        self._spectrum.observe(float(header["spectrum_i_max"]))
        self._invalidate_components()
        self._bind_native()  # os arrays foram trocados: o kernel volta a apontar para eles
        self._frozen = self._build_state([]) if self._locked else None

    @staticmethod
    def _parse_snapshot(blob: bytes) -> tuple[Mapping[str, Any], bytes]:
        if not blob.startswith(SNAPSHOT_MAGIC):
            raise ValueError("cabeçalho mágico ausente")
        start = len(SNAPSHOT_MAGIC)
        if len(blob) < start + 8:
            raise ValueError("snapshot truncado")
        (length,) = struct.unpack("<Q", blob[start : start + 8])
        raw = blob[start + 8 : start + 8 + length]
        payload = blob[start + 8 + length :]
        header = json.loads(raw.decode("utf-8"))
        if not isinstance(header, dict):
            raise ValueError("cabeçalho não é objeto JSON")
        if hashlib.sha256(payload).hexdigest() != header.get("payload_sha256"):
            raise ValueError("SHA-256 do payload não confere")
        return header, payload
