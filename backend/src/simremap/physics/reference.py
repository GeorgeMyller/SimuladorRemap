"""Piloto de referência em malha aberta e banco de rotação constante (physics seção 10).

No Sprint 1 a física é exercitada sem a ECU: o ``ReferenceDriver`` converte a
``ReferenceCommandSchedule`` do catálogo (comandos por RPM a plena carga) em
``ActuatorCommands``. A massa de combustível usa a massa de ar física (piloto "ideal",
privilegiado), com o pulso calculado pela leitura de pressão de combustível, como faria
uma ECU com VE perfeita. O boost alvo (``map_target_kpa``) é seguido por um PI sobre o
duty da wastegate com pré-alimentação pela pressão de mola.

``RpmHoldRig`` emula um banco de motor que segura a rotação (carga PI sobre o erro de rpm)
para varreduras em regime permanente.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from simremap.catalog.contracts import ReferenceCommandPoint, ReferenceCommandSchedule
from simremap.dyno.contracts import AmbientConditions, DynoLoad
from simremap.physics.contracts import ActuatorCommands, EngineState, SensorReadings
from simremap.physics.engine import PhysicsEngine

__all__ = ["ReferenceDriver", "RpmHoldRig", "free_load", "interpolate_schedule", "replay_digest"]

BOOST_KP = 0.05  # %/kPa
BOOST_KI = 0.4  # %/(kPa·s)
DUTY_MAX_PCT = 100.0
BOOST_I_ZONE_KPA = 15.0  # o integral só atua perto do alvo (evita windup no enchimento)


def interpolate_schedule(schedule: ReferenceCommandSchedule, rpm: float) -> ReferenceCommandPoint:
    """Ponto da tabela interpolado linearmente em rpm (saturado nas pontas)."""
    pts = schedule.points
    if rpm <= pts[0].rpm:
        return pts[0]
    if rpm >= pts[-1].rpm:
        return pts[-1]
    for a, b in itertools.pairwise(pts):
        if a.rpm <= rpm <= b.rpm:
            f = (rpm - a.rpm) / (b.rpm - a.rpm)

            def lerp(x: float, y: float, f: float = f) -> float:
                return x + (y - x) * f

            return ReferenceCommandPoint(
                rpm=rpm,
                throttle_pct=lerp(a.throttle_pct, b.throttle_pct),
                ignition_advance_deg=lerp(a.ignition_advance_deg, b.ignition_advance_deg),
                lambda_target=lerp(a.lambda_target, b.lambda_target),
                map_target_kpa=lerp(a.map_target_kpa, b.map_target_kpa),
                wastegate_duty_pct=lerp(a.wastegate_duty_pct, b.wastegate_duty_pct),
                vvt_intake_deg=lerp(a.vvt_intake_deg, b.vvt_intake_deg),
                vvt_exhaust_deg=lerp(a.vvt_exhaust_deg, b.vvt_exhaust_deg),
            )
    return pts[-1]  # pragma: no cover - inalcançável com pontos crescentes


class ReferenceDriver:
    """Comandos de malha aberta a partir da ``ReferenceCommandSchedule``."""

    def __init__(
        self,
        engine: PhysicsEngine,
        schedule: ReferenceCommandSchedule,
        *,
        throttle_pct: float | None = None,
        lambda_target: float | None = None,
        advance_offset_deg: float = 0.0,
        advance_deg: float | None = None,
        ve_error: float = 1.0,
        boost_control: bool = True,
    ) -> None:
        self.engine = engine
        self.schedule = schedule
        self.throttle_override = throttle_pct
        self.lambda_override = lambda_target
        self.advance_offset = advance_offset_deg
        self.advance_override = advance_deg
        self.ve_error = ve_error
        self.boost_control = boost_control
        self.integral = 0.0
        self.fuel_cut: list[bool] = [False] * engine.n_cyl
        self.spark_cut: list[bool] = [False] * engine.n_cyl
        self.pulse_scale = 1.0
        self.duty_override: float | None = None
        self.bypass_open = False

    def point(self) -> ReferenceCommandPoint:
        return interpolate_schedule(self.schedule, self.engine.rpm)

    def commands(self, sensors: SensorReadings | None, dt: float) -> ActuatorCommands:
        eng = self.engine
        pt = self.point()
        lam_t = self.lambda_override if self.lambda_override is not None else pt.lambda_target
        m_air = eng.trapped_air_kg() * self.ve_error
        m_fuel = m_air / (lam_t * eng.fuel.afr_stoich)
        dp = sensors.fuel_pressure_kpa if sensors is not None else eng.injection_dp_kpa()
        vbat = sensors.battery_v if sensors is not None else eng.battery_v()
        pulse = eng.injector.pulse_for_mass_ms(m_fuel, dp, vbat) * self.pulse_scale
        pulse = min(max(pulse, 0.0), 50.0)
        adv = (
            self.advance_override
            if self.advance_override is not None
            else (pt.ignition_advance_deg + self.advance_offset)
        )
        adv = min(max(adv, -30.0), 60.0)
        throttle = self.throttle_override if self.throttle_override is not None else pt.throttle_pct
        duty = self._boost_duty(pt, sensors, dt)
        n = eng.n_cyl
        return ActuatorCommands.model_construct(
            t_sim_s=eng.t_sim_s,
            injector_pw_ms=[pulse] * n,
            injection_end_deg_btdc=None,
            ignition_advance_deg=[adv] * n,
            fuel_cut=list(self.fuel_cut),
            spark_cut=list(self.spark_cut),
            throttle_pct=throttle,
            wastegate_duty_pct=duty,
            vvt_intake_target_deg=pt.vvt_intake_deg,
            vvt_exhaust_target_deg=pt.vvt_exhaust_deg,
            bypass_open=self.bypass_open,
            antilag_air_pct=0.0,
            fuel_pump_duty_pct=100.0,
        )

    def _boost_duty(
        self, pt: ReferenceCommandPoint, sensors: SensorReadings | None, dt: float
    ) -> float:
        if self.duty_override is not None:
            return self.duty_override
        turbo = self.engine.vehicle.turbo
        if turbo is None or not self.boost_control:
            return pt.wastegate_duty_pct
        p_amb = self.engine.vars.p_amb_kpa
        gauge = max(pt.map_target_kpa - p_amb, 1.0)
        ff = min(max(1.0 - turbo.wastegate_spring_kpa / gauge, 0.0), 1.0) * 100.0
        map_now = sensors.map_kpa if sensors is not None else self.engine.vars.p_man_kpa
        err = pt.map_target_kpa - map_now
        unsat = ff + BOOST_KP * err + self.integral
        # Anti-windup: só integra enquanto o duty não está saturado no sentido do erro.
        saturated = (unsat >= DUTY_MAX_PCT and err > 0.0) or (unsat <= 0.0 and err < 0.0)
        if abs(err) < BOOST_I_ZONE_KPA and not saturated:
            self.integral = min(max(self.integral + BOOST_KI * err * dt, -40.0), 40.0)
        return min(max(ff + BOOST_KP * err + self.integral, 0.0), 100.0)


@dataclass(slots=True)
class RpmHoldRig:
    """Banco que segura a rotação com carga PI (modo regime permanente)."""

    target_rpm: float
    inertia_kg_m2: float = 0.5
    kp: float = 2.0
    ki: float = 20.0
    integral: float = 0.0
    ambient: AmbientConditions | None = None

    def load(self, state: EngineState | None, rpm: float, dt: float) -> DynoLoad:
        err = rpm - self.target_rpm
        self.integral = min(max(self.integral + self.ki * err * dt, -2000.0), 4000.0)
        base = state.torque_nm if state is not None else 0.0
        torque = max(base + self.kp * err + self.integral, 0.0)
        return DynoLoad.model_construct(
            reflected_inertia_kg_m2=self.inertia_kg_m2,
            load_torque_crank_nm=torque,
            gear=0,
            wheel_to_crank_ratio=0.0,
            pedal_pct=100.0,
            fan_air_speed_m_s=15.0,
            ambient=self.ambient or AmbientConditions(),
            vehicle_speed_kmh=0.0,
            clutch_pressed=False,
            launch_switch=False,
            shift_request=False,
            antilag_switch=False,
        )


def free_load(
    inertia_kg_m2: float = 0.0,
    torque_nm: float = 0.0,
    ambient: AmbientConditions | None = None,
    fan_m_s: float = 15.0,
) -> DynoLoad:
    """``DynoLoad`` fixo (sem controlo)."""
    return DynoLoad.model_construct(
        reflected_inertia_kg_m2=inertia_kg_m2,
        load_torque_crank_nm=torque_nm,
        gear=0,
        wheel_to_crank_ratio=0.0,
        pedal_pct=0.0,
        fan_air_speed_m_s=fan_m_s,
        ambient=ambient or AmbientConditions(),
        vehicle_speed_kmh=0.0,
        clutch_pressed=False,
        launch_switch=False,
        shift_request=False,
        antilag_switch=False,
    )


def replay_digest(
    vehicle_json: str,
    fuel_json: str,
    *,
    seed: int = 0,
    sim_hz: int = 1000,
    seconds: float = 30.0,
    rpm_start: float = 2500.0,
    rpm_end: float = 6000.0,
) -> str:
    """Executa uma puxada de referência determinística e devolve o ``state_digest`` final.

    Função de módulo (serializável) para verificar o determinismo em processos separados
    (RF-20): o mesmo veículo, combustível, ``seed`` e ``sim_hz`` dão sempre o mesmo digest.
    A rotação segue uma rampa linear ``rpm_start → rpm_end`` segurada pelo ``RpmHoldRig``,
    com ruído ligado e ``read_sensors`` em todos os ticks (ordem do barramento).
    """
    from simremap.catalog.contracts import FuelSpec, VehicleSpec  # noqa: PLC0415
    from simremap.physics.contracts import PhysicsConfig  # noqa: PLC0415

    vehicle = VehicleSpec.model_validate_json(vehicle_json)
    fuel = FuelSpec.model_validate_json(fuel_json)
    engine = PhysicsEngine(
        PhysicsConfig(sim_hz=sim_hz, seed=seed), vehicle, fuel, initial_ect_c=90.0
    )
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule)
    dt = engine.resolved.dt
    n = round(seconds * sim_hz)
    rig = RpmHoldRig(target_rpm=rpm_start)
    engine.crank(rpm_start)
    state: EngineState | None = None
    for k in range(n):
        rig.target_rpm = rpm_start + (rpm_end - rpm_start) * k / max(n - 1, 1)
        sensors = engine.read_sensors()
        commands = driver.commands(sensors, dt)
        state = engine.step(commands, rig.load(state, engine.rpm, dt), dt)
    return engine.state_digest()
