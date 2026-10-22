"""Auxiliares dos testes do knock-and-failure-model (eventos e estados sintéticos).

Importado pelos testes como ``kfm_helpers`` (o ``conftest.py`` põe esta pasta no
``sys.path``, porque ``tests/`` não é pacote).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.damage.config import DamageConfig
from simremap.damage.contracts import DamageState, ForensicReport
from simremap.damage.forensic import build_forensic_report
from simremap.damage.knock import ATM_KPA, DE_ACTIVATION_K, DE_COEFF_MS, DE_ON_EXP, ms_per_degree
from simremap.damage.model import DamageModel
from simremap.dyno.contracts import DynoRun
from simremap.ecu.contracts import EcuStatus
from simremap.physics.contracts import CombustionEvent, EngineState

SHA = "a" * 64
SESSION = "0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c"
RUN = "01JAB0000000000000000000CD"
E27_RON = 95.0
E27_MON = 81.0
LHV = 43.0  # MJ/kg (escolhido para Q_disp redondo)
AFR = 13.2
LEAD_P_KPA = 15_000.0

# Coeficientes literais das RFs da spec (os números de verificação das RFs usam-nos). O
# ``DamageConfig`` padrão (1.2.0) traz a calibração do laço física + ECU de série:
# τ de Douaud-Eyzat × 4,25 e LSPI com limiar de 2700 kPa e probabilidades 10× menores.
SPEC_COEFFICIENTS: dict[str, Any] = {
    "knock_tau_multiplier": 1.0,
    "lspi_imep_min_kpa": 1500.0,
    "lspi_p_base": 1.0e-4,
    "lspi_p_max": 2.0e-3,
}


def spec_config(**over: Any) -> DamageConfig:
    """``DamageConfig`` com os coeficientes literais da spec (mais ``over``)."""
    return DamageConfig(**{**SPEC_COEFFICIENTS, **over})


SPEC_CONFIG = spec_config()


def _grid2d(x_name: str, y_name: str, xs: list[float], ys: list[float], v: float) -> dict[str, Any]:
    return {
        "x_name": x_name,
        "x_values": xs,
        "y_name": y_name,
        "y_values": ys,
        "z_values": [[v] * len(xs) for _ in ys],
    }


def _schedule(vehicle_id: str) -> dict[str, Any]:
    return {
        "vehicle_id": vehicle_id,
        "fuel_id": "e27",
        "points": [
            {
                "rpm": 2000.0 + 250.0 * i,
                "ignition_advance_deg": 10.0,
                "lambda_target": 0.82,
                "map_target_kpa": 180.0,
            }
            for i in range(19)
        ],
    }


def _engine(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "architecture": "inline",
        "n_cyl": 4,
        "bore_mm": 82.5,
        "stroke_mm": 92.8,
        "rod_length_mm": 144.0,
        "compression_ratio": 9.6,
        "displacement_cc": 1984.0,
        "valvetrain": "dohc",
        "valves_per_cyl": 4,
        "firing_order": [1, 3, 4, 2],
        "ivc_deg_abdc": 40.0,
        "evo_deg_bbdc": 45.0,
        "injection_type": "gdi",
        "throttle_diameter_mm": 56.0,
        "intake_manifold_volume_l": 2.5,
        "boost_volume_l": 3.0,
        "exhaust_manifold_volume_l": 1.0,
        "recip_mass_g": 600.0,
        "true_ve": _grid2d("rpm", "map_kpa", [1000.0, 4000.0, 7000.0], [30.0, 100.0, 250.0], 0.9),
    }
    data.update(over)
    return data


def _limits(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "rod_torque_limit_nm": 420.0,
        "max_rod_load_kn": 52.0,
        "max_cylinder_pressure_bar": 120.0,
        "egt_max_c": 950.0,
        "max_rpm": 6800.0,
        "rev_limit_rpm": 6500.0,
        "valve_float_rpm": 7200.0,
        "turbo_max_rpm": 210000.0,
        "max_piston_temp_c": 330.0,
    }
    data.update(over)
    return data


def _turbo() -> dict[str, Any]:
    return {
        "housing": "single_scroll",
        "rotor_inertia_kg_m2": 2e-5,
        "bearing_friction_k": 1e-8,
        "turbine_area_eff_cm2": 8.0,
        "turbine_efficiency": {
            "x_name": "pressure_ratio",
            "x_values": [1.0, 2.0, 3.0],
            "values": [0.6, 0.7, 0.65],
        },
        "wastegate_kind": "internal",
        "wastegate_area_max_cm2": 3.0,
        "wastegate_spring_kpa": 60.0,
        "compressor": {
            "pr_design": 2.5,
            "n_design_rpm": 180000,
            "n_max_rpm": 230000,
            "m_choke_max_kg_s": 0.25,
            "eta_max": 0.76,
            "m_peak_kg_s": 0.15,
            "m_range_kg_s": 0.1,
            "n_peak_rpm": 150000,
        },
    }


def vehicle_data(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "vehicle_id": "hatch-20t-gdi",
        "display_name": "Hatch 2.0 turbo GDI",
        "architecture_note": "4 cilindros em linha, turbo, injeção direta",
        "body": "hatch",
        "data_version": 1,
        "validation_status": "validated",
        "validated_on": "2026-10-01",
        "induction": "turbo",
        "engine": _engine(),
        "turbo": _turbo(),
        "injectors": {
            "flow_cc_min": 900.0,
            "dp_ref_kpa": 10000.0,
            "rail_pressure_min_kpa": 5000.0,
            "rail_pressure_max_kpa": 20000.0,
            "pressure_reference": "cylinder",
            "dead_time_ms": _grid2d(
                "battery_v", "dp_kpa", [8.0, 12.0, 16.0], [5000.0, 10000.0, 20000.0], 0.5
            ),
        },
        "stock_fuel_id": "e27",
        "allowed_fuel_ids": ["e27", "e100", "podium"],
        "drive_layout": "fwd",
        "gear_ratios": [3.5, 2.1, 1.4, 1.0, 0.8, 0.65],
        "final_drive_ratio": 3.9,
        "tire_radius_m": 0.31,
        "drivetrain_efficiency": 0.85,
        "driveline_inertia_kg_m2": 2.0,
        "mechanical_limits": _limits(),
        "rated": {
            "peak_power_whp": 200.0,
            "peak_power_rpm": 5500.0,
            "peak_torque_nm": 350.0,
            "peak_torque_rpm_from": 1800.0,
            "peak_torque_rpm_to": 4500.0,
        },
        "stock_profile_id": "oem-stage",
        "stock_calibration_id": "stock-hatch-20t-gdi-oem-stage",
        "factory_calibrations": [
            {
                "profile_id": "oem-stage",
                "calibration_id": "stock-hatch-20t-gdi-oem-stage",
                "file": "calibrations/oem-stage.json",
                "sha256": SHA,
            }
        ],
        "reference_command_schedule": _schedule("hatch-20t-gdi"),
        "reference_curve_ids": ["stock-e27"],
    }
    data.update(over)
    return data


def build_hatch() -> VehicleSpec:
    return VehicleSpec.model_validate(vehicle_data())


def build_v8() -> VehicleSpec:
    data = vehicle_data(
        vehicle_id="muscle-v8-sc",
        induction="supercharger",
        turbo=None,
        supercharger={
            "sc_type": "roots",
            "displacement_l_per_rev": 1.9,
            "pulley_ratio": 2.4,
            "adiabatic_efficiency": {
                "x_name": "pressure_ratio",
                "x_values": [1.0, 2.0],
                "values": [0.6, 0.55],
            },
            "max_rotor_rpm": 16000,
        },
        mechanical_limits=_limits(
            turbo_max_rpm=None, rod_torque_limit_nm=900.0, max_rod_load_kn=70.0
        ),
        rated={
            "peak_power_whp": 500.0,
            "peak_power_rpm": 6000.0,
            "peak_torque_nm": 700.0,
            "peak_torque_rpm_from": 3000.0,
            "peak_torque_rpm_to": 5000.0,
        },
        stock_calibration_id="stock-muscle-v8-sc-oem-stage",
        factory_calibrations=[
            {
                "profile_id": "oem-stage",
                "calibration_id": "stock-muscle-v8-sc-oem-stage",
                "file": "calibrations/oem-stage.json",
                "sha256": SHA,
            }
        ],
        reference_command_schedule=_schedule("muscle-v8-sc"),
        engine=_engine(
            architecture="v",
            n_cyl=8,
            v_angle_deg=90.0,
            bore_mm=103.25,
            stroke_mm=92.0,
            displacement_cc=6162.0,
            firing_order=[1, 8, 7, 2, 6, 5, 4, 3],
            injection_type="pfi",
            throttle_location="pre_compressor",
            boost_volume_l=None,
        ),
    )
    return VehicleSpec.model_validate(data)


def build_e27(**over: Any) -> FuelSpec:
    data: dict[str, Any] = {
        "fuel_id": "e27",
        "display_name": "Gasolina E27",
        "afr_stoich": AFR,
        "lhv_mj_kg": LHV,
        "ron": E27_RON,
        "mon": E27_MON,
        "knock_on": 88.0,
        "h_fg_kj_kg": 420.0,
        "density_kg_m3": 745.0,
        "ethanol_mass_fraction": 0.27,
        "laminar_bm_m_s": 0.35,
        "laminar_bphi_m_s": -0.55,
        "laminar_phi_m": 1.1,
        "preignition_surface_temp_c": 820.0,
    }
    data.update(over)
    return FuelSpec.model_validate(data)


ModelFactory = Callable[..., DamageModel]


# --------------------------------------------------------------------------- eventos


def t_unburned_for_tau(tau_ms: float, p_kpa: float, octane: float = 88.0) -> float:
    """``T_u`` (K) que dá ``τ`` em ``p`` por Douaud-Eyzat."""
    base = DE_COEFF_MS * (octane / 100.0) ** DE_ON_EXP * (p_kpa / ATM_KPA) ** -1.7
    return DE_ACTIVATION_K / math.log(tau_ms / base)


def make_event(
    cylinder: int,
    t_sim_s: float,
    rpm: float,
    *,
    knock: bool = False,
    xb_k: float = 0.8,
    p_k: float = 8000.0,
    p_max_kpa: float = 9000.0,
    rod_force_n: float = 30_000.0,
    imep_kpa: float = 1000.0,
    lambda_real: float | None = 0.85,
    misfire: bool = False,
    theta_onset: float = -20.0,
    validated: bool = False,
) -> CombustionEvent:
    """Evento de 40 pontos; com ``knock`` a integral passa de 1 no 1.º ponto."""
    n = 40
    theta_start = theta_onset
    if knock:
        # 1.º ponto leva I_LW a 0,999; o 2.º (θ_onset) cruza 1 com p_k e x_b,k
        t_lead = t_unburned_for_tau(ms_per_degree(rpm) / 0.999, LEAD_P_KPA)
        pressure = [LEAD_P_KPA] + [p_k] * (n - 1)
        t_u = [t_lead] + [3000.0] * (n - 1)
        xb = [0.0, xb_k] + [min(0.999, xb_k + 0.005 * i) for i in range(1, n - 1)]
        theta_start = theta_onset - 1.0
    else:
        pressure = [3000.0] * n
        t_u = [700.0] * n
        xb = [min(1.0, i / (n - 1)) for i in range(n)]
    data: dict[str, Any] = {
        "cylinder": cylinder,
        "t_sim_s": t_sim_s,
        "rpm": rpm,
        "theta_start_deg": theta_start,
        "pressure_kpa": pressure,
        "t_unburned_k": t_u,
        "burned_fraction": xb,
        "p_max_kpa": p_max_kpa,
        "theta_pmax_deg_atdc": 15.0,
        "t_unburned_max_k": max(t_u),
        "rod_force_peak_n": rod_force_n,
        "imep_gross_kpa": imep_kpa,
        "lambda_real": lambda_real,
        "fuel_octane_ron": E27_RON,
        "fuel_octane_mon": E27_MON,
        "misfire": misfire,
        "afterfire_energy_j": 0.0,
        "pop_event": False,
    }
    if validated:
        return CombustionEvent.model_validate(data)
    return CombustionEvent.model_construct(**data)


def fuel_mass_for_energy(q_disp_j: float, eta: float = 0.98) -> float:
    """``m_fuel`` (mg) que dá ``Q_disp`` com o ``LHV`` do E27 de teste."""
    return q_disp_j / (eta * LHV)


def make_state(
    tick: int,
    t_sim_s: float,
    rpm: float,
    n_cyl: int = 4,
    events: list[CombustionEvent] | None = None,
    *,
    validated: bool = False,
    **over: Any,
) -> EngineState:
    m_fuel = over.pop("m_fuel_mg", fuel_mass_for_energy(1935.0))
    per_cyl: dict[str, Any] = {
        "ve_true": [0.95] * n_cyl,
        "m_air_mg": [1000.0] * n_cyl,
        "m_fuel_mg": [m_fuel] * n_cyl,
        "lambda_cyl": [0.85] * n_cyl,
        "ignition_advance_deg": [15.0] * n_cyl,
        "burn_duration_deg": [40.0] * n_cyl,
        "p_max_kpa": [9000.0] * n_cyl,
        "theta_pmax_deg_atdc": [15.0] * n_cyl,
        "t_unburned_max_k": [900.0] * n_cyl,
        "rod_force_peak_n": [30_000.0] * n_cyl,
        "piston_temp_c": [100.0] * n_cyl,
        "hot_spot_temp_c": [500.0] * n_cyl,
        "egt_c": [850.0] * n_cyl,
    }
    data: dict[str, Any] = {
        "t_sim_s": t_sim_s,
        "tick": tick,
        "rpm": rpm,
        "crank_angle_deg": 0.0,
        "locked": False,
        "stalled": False,
        "map_kpa": 200.0,
        "boost_pre_throttle_kpa": 205.0,
        "exhaust_manifold_kpa": 220.0,
        "t_manifold_c": 40.0,
        "t_intercooler_out_c": 40.0,
        "lambda_collector": 0.85,
        "egt_collector_c": 900.0,
        "imep_gross_kpa": 1800.0,
        "pmep_kpa": 50.0,
        "fmep_kpa": 150.0,
        "torque_indicated_nm": 380.0,
        "torque_nm": 300.0,
        "power_kw": 150.0,
        "wheel_power_kw": 130.0,
        "whp": 174.0,
        "fuel_flow_g_s": 12.0,
        "bsfc_g_kwh": 280.0,
        "thermal_efficiency": 0.33,
        "turbo_rpm": 150_000.0,
        "compressor_pressure_ratio": 2.0,
        "compressor_efficiency": 0.7,
        "surge_margin": 0.2,
        "wastegate_position_pct": 20.0,
        "supercharger_rpm": None,
        "supercharger_power_kw": None,
        "ect_c": 90.0,
        "iat_c": 40.0,
        "events": events or [],
        "real_time_factor": None,
        **per_cyl,
    }
    for key, value in over.items():
        broadcast = key in per_cyl and not isinstance(value, list)
        data[key] = [value] * n_cyl if broadcast else value
    if validated:
        return EngineState.model_validate(data)
    return EngineState.model_construct(**data)


def make_ecu(n_cyl: int = 4, retard: float | list[float] = 0.0, **over: Any) -> EcuStatus:
    retard_list = retard if isinstance(retard, list) else [retard] * n_cyl
    data: dict[str, Any] = {
        "t_sim_s": 0.0,
        "lambda_target": 0.85,
        "stft_pct": 0.0,
        "ltft_pct": 0.0,
        "closed_loop_active": False,
        "fuel_mass_mg": [45.0] * n_cyl,
        "injector_pw_ms": [5.0] * n_cyl,
        "inj_duty_pct": 40.0,
        "ignition_advance_deg": [15.0] * n_cyl,
        "knock_retard_deg": retard_list,
        "boost_target_kpa": 200.0,
        "wastegate_duty_pct": 50.0,
        "limiter_state": "off",
        "active_strategies": [],
        "arbitration_winner": "normal",
        "failsafe_actions": [],
        "load_pct": 150.0,
        "torque_request_nm": None,
        "calibration_hash": SHA,
    }
    data.update(over)
    return EcuStatus.model_construct(**data)


EventFactory = Callable[[int, float, float], CombustionEvent]
StateOverrides = Callable[[float], dict[str, Any]]
EcuFactory = Callable[[float], EcuStatus | None]


def quiet(cylinder: int, t: float, rpm: float) -> CombustionEvent:
    return make_event(cylinder, t, rpm)


@dataclass
class Driver:
    """Gera ticks a ``sim_hz`` com eventos de combustão na ordem de ignição."""

    model: DamageModel
    rpm: float
    firing_order: tuple[int, ...] = (1, 3, 4, 2)
    sim_hz: int = 1000
    event_factory: EventFactory = quiet
    state_overrides: StateOverrides | None = None
    ecu_factory: EcuFactory | None = None
    tick: int = 0
    states: list[DamageState] = field(default_factory=list)
    keep_states: bool = False

    def _events(self, t0: float, t1: float) -> list[CombustionEvent]:
        if self.rpm <= 0:
            return []
        period = 120.0 / self.rpm
        n = len(self.firing_order)
        events: list[CombustionEvent] = []
        for j, cylinder in enumerate(self.firing_order):
            offset = j * period / n
            m = math.floor((t0 - offset) / period) + 1
            t = offset + m * period
            while t <= t1 + 1e-12:
                if t > t0 + 1e-12:
                    events.append(self.event_factory(cylinder, round(t, 9), self.rpm))
                t += period
        return events

    def run(self, seconds: float, until_locked: bool = False) -> Iterator[DamageState]:
        dt = 1.0 / self.sim_hz
        ticks = round(seconds * self.sim_hz)
        for _ in range(ticks):
            self.tick += 1
            t1 = self.tick * dt
            events = self._events(t1 - dt, t1)
            over = self.state_overrides(t1) if self.state_overrides else {}
            state = make_state(self.tick, t1, self.rpm, len(self.firing_order), events, **over)
            ecu = self.ecu_factory(t1) if self.ecu_factory else None
            result = self.model.step(state, dt, ecu)
            if self.keep_states:
                self.states.append(result)
            yield result
            if until_locked and result.engine_locked:
                return

    def advance(self, seconds: float, until_locked: bool = False) -> DamageState | None:
        last: DamageState | None = None
        for last in self.run(seconds, until_locked):  # noqa: B007
            pass
        return last


# ------------------------------------------------- jornada do Lucas (sintética)

T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def dyno_run(run_id: str = RUN, state: str = "engine_failed", **over: Any) -> DynoRun:
    data: dict[str, Any] = {
        "run_id": run_id,
        "session_id": SESSION,
        "run_type": "sweep_pull",
        "request": {"run_type": "sweep_pull"},
        "state": state,
        "started_at_tick": 0,
        "calibration_id": "cal-lucas",
        "calibration_hash": SHA,
        "seed": 42,
        "sim_hz": 1000,
    }
    data.update(over)
    return DynoRun.model_validate(data)


def lucas_events(c: int, t: float, rpm: float) -> Any:
    if t >= 2.0 and c == 3:
        return make_event(c, t, rpm, knock=True, p_k=8000.0, theta_onset=12.0)
    if t >= 1.0 and c in (2, 3):
        return make_event(c, t, rpm, knock=True, p_k=2000.0, theta_onset=14.0)
    return make_event(c, t, rpm)


def lucas_ecu(t: float) -> EcuStatus:
    ramp = min(8.0, max(0.0, (t - 1.2) / 0.4 * 8.0))
    return make_ecu(retard=[0.0, 2.0 if t >= 1.0 else 0.0, ramp, 0.0], boost_target_kpa=280.0)


def run_lucas(
    model: DamageModel, ecu: Any = lucas_ecu, seconds: float = 20.0, run_id: str = RUN
) -> None:
    driver = Driver(
        model,
        5000.0,
        event_factory=lucas_events,
        state_overrides=lambda _t: {"lambda_collector": 0.86, "map_kpa": 200.0},
        ecu_factory=ecu,
    )
    model.set_run(run_id)
    driver.advance(seconds, until_locked=True)


def lucas_report(model: DamageModel, **kw: Any) -> ForensicReport:
    return build_forensic_report(
        model.freeze_trace(),
        dyno_run(),
        kw.pop("baseline", None),
        kw.pop("diff", None),
        kw.pop("kind", "failure"),
        created_at=kw.pop("created_at", T0),
    )
