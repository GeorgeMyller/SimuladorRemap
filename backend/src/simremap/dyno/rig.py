"""Rolo inercial, perdas, absorvedor de Foucault e medição (dyno RF-04, RF-05, RF-12).

Acoplamento roda-rolo rígido (NG-01). Com ``G = gear_ratio(gear) · final_drive`` e
``k = r_tire / r_roll``:

- ``ω_roll = ω_crank · k / G``;
- inércia refletida no virabrequim ``J_refl = (J_roll · k² + J_drv_wheel) / G²``;
- carga refletida ``T_load_crank = (T_abs + T_loss) · k / G``;
- perdas do rolo ``T_loss = c0 + c1 · ω_roll`` (só com o rolo a girar);
- absorvedor ``dT_abs/dt = (T_cmd − T_abs) / τ_abs`` com capacidade
  ``T_max(ω) = T_cap · (1 − exp(−ω_roll / ω_c))``, potência máxima ``P_max`` e
  ``T_cmd ∈ 0..T_max`` (o absorvedor não motoriza).

A física integra ``(T_brake − T_load) / (J_eng + J_refl)``; para reproduzir a equação da
spec ``α = (η_drv · T_brake − T_load_crank) / (J_eng + J_refl)`` o ``DynoLoad`` soma a
perda da transmissão ``(1 − η_drv) · T_brake`` do tick anterior e a perda fixa
``drivetrain_fixed_loss_kw / ω_crank``.

Medição (como um rolo inercial real): ``α_roll`` por diferença central numa janela de
``accel_window_ticks`` (ímpar); ``P_wheel = (J_roll · α_roll + T_abs + T_loss) · ω_roll``;
``T_wheel = P_wheel / ω_wheel``; ``T_eng = T_wheel / (G · η_drv)``; ``P_crank = P_wheel / η_drv``.

Em ponto morto (``gear = 0``) o rolo fica desacoplado e desacelera pelas próprias perdas e
pelo absorvedor: ``J_roll · dω/dt = −(T_abs + T_loss)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, cast

from simremap.catalog.contracts import VehicleSpec
from simremap.dyno.contracts import AmbientConditions, DynoLoad, DynoRigConfig

__all__ = [
    "HP_KW",
    "RPM_TO_RAD_S",
    "AccelerationWindow",
    "Driveline",
    "EddyCurrentAbsorber",
    "RollMeasurement",
    "RollerRig",
    "measure_roll",
]

RPM_TO_RAD_S: Final = math.pi / 30.0
HP_KW: Final = 0.7457  # kW por hp (whp = kW / 0,7457)
MS_TO_KMH: Final = 3.6
_MIN_OMEGA: Final = 1e-9


@dataclass(frozen=True, slots=True)
class Driveline:
    """Transmissão do veículo vista pelo rolo."""

    gear_ratios: tuple[float, ...]
    final_drive: float
    tire_radius_m: float
    roller_radius_m: float
    efficiency: float
    fixed_loss_kw: float
    driveline_inertia_kg_m2: float

    @classmethod
    def from_vehicle(cls, vehicle: VehicleSpec, rig: DynoRigConfig) -> Driveline:
        return cls(
            gear_ratios=tuple(vehicle.gear_ratios),
            final_drive=vehicle.final_drive_ratio,
            tire_radius_m=vehicle.tire_radius_m,
            roller_radius_m=rig.roller_radius_m,
            efficiency=vehicle.drivetrain_efficiency,
            fixed_loss_kw=vehicle.drivetrain_fixed_loss_kw,
            driveline_inertia_kg_m2=vehicle.driveline_inertia_kg_m2,
        )

    @property
    def n_gears(self) -> int:
        return len(self.gear_ratios)

    @property
    def k(self) -> float:
        """``k = r_tire / r_roll``."""
        return self.tire_radius_m / self.roller_radius_m

    def overall_ratio(self, gear: int) -> float:
        """``G = gear_ratio · final_drive``; ``0`` em ponto morto."""
        if gear <= 0:
            return 0.0
        if gear > self.n_gears:
            raise ValueError(f"marcha {gear} acima de {self.n_gears}")
        return self.gear_ratios[gear - 1] * self.final_drive

    def wheel_to_crank_ratio(self, gear: int) -> float:
        """``G / k`` (rotação do virabrequim por rotação do rolo)."""
        g = self.overall_ratio(gear)
        return g / self.k if g > 0.0 else 0.0

    def reflected_inertia(self, gear: int, roller_inertia_kg_m2: float) -> float:
        """``J_refl = (J_roll · k² + J_drv) / G²`` (kg·m²)."""
        g = self.overall_ratio(gear)
        if g <= 0.0:
            return 0.0
        return (roller_inertia_kg_m2 * self.k**2 + self.driveline_inertia_kg_m2) / g**2

    def roller_omega(self, rpm: float, gear: int) -> float:
        """``ω_roll = ω_crank · k / G`` (rad/s)."""
        g = self.overall_ratio(gear)
        if g <= 0.0:
            return 0.0
        return max(rpm, 0.0) * RPM_TO_RAD_S * self.k / g

    def crank_rpm(self, omega_roll: float, gear: int) -> float:
        """RPM do virabrequim equivalente a ``ω_roll`` na marcha ``gear``."""
        g = self.overall_ratio(gear)
        if g <= 0.0:
            return 0.0
        return omega_roll * g / self.k / RPM_TO_RAD_S


class EddyCurrentAbsorber:
    """Absorvedor de Foucault de 1.ª ordem com capacidade dependente da velocidade."""

    __slots__ = ("cap_nm", "max_power_w", "omega_c", "tau_s", "torque_nm")

    def __init__(self, config: DynoRigConfig) -> None:
        self.tau_s = config.absorber_tau_s
        self.cap_nm = config.absorber_cap_nm
        self.omega_c = config.absorber_omega_c_rad_s
        self.max_power_w = config.absorber_max_power_kw * 1000.0
        self.torque_nm = 0.0

    def capacity(self, omega_roll: float) -> float:
        """``min(T_cap · (1 − exp(−ω/ω_c)), P_max / ω)`` (N·m)."""
        if omega_roll <= 0.0:
            return 0.0
        by_speed = self.cap_nm * (1.0 - math.exp(-omega_roll / self.omega_c))
        return min(by_speed, self.max_power_w / omega_roll)

    def step(self, command_nm: float, omega_roll: float, dt: float) -> float:
        """Avança ``dt`` em direção a ``clamp(command, 0, T_max)`` e devolve ``T_abs``."""
        cap = self.capacity(omega_roll)
        target = min(max(command_nm, 0.0), cap)
        self.torque_nm += (1.0 - math.exp(-dt / self.tau_s)) * (target - self.torque_nm)
        self.torque_nm = min(max(self.torque_nm, 0.0), cap)
        return self.torque_nm

    def reset(self) -> None:
        self.torque_nm = 0.0


class RollerRig:
    """Rolo inercial com absorvedor; produz o ``DynoLoad`` de cada tick."""

    __slots__ = (
        "absorber",
        "ambient",
        "config",
        "driveline",
        "gear",
        "last_absorber_nm",
        "last_loss_nm",
        "omega_roll",
    )

    def __init__(
        self, config: DynoRigConfig, driveline: Driveline, ambient: AmbientConditions
    ) -> None:
        self.config = config
        self.driveline = driveline
        self.ambient = ambient
        self.absorber = EddyCurrentAbsorber(config)
        self.gear = 0
        self.omega_roll = 0.0
        self.last_absorber_nm = 0.0
        self.last_loss_nm = 0.0

    @property
    def roller_inertia(self) -> float:
        return self.config.roller_inertia_kg_m2

    def loss_torque(self, omega_roll: float) -> float:
        """``T_loss = c0 + c1 · ω_roll`` com o rolo a girar; 0 parado."""
        if omega_roll <= 0.0:
            return 0.0
        return self.config.loss_c0_nm + self.config.loss_c1_nm_s_rad * omega_roll

    def engage(self, gear: int, rpm: float) -> None:
        """Engata ``gear`` (0 = ponto morto); acoplado, o rolo sincroniza com o motor."""
        if gear < 0 or gear > self.driveline.n_gears:
            raise ValueError(f"marcha {gear} fora de 0..{self.driveline.n_gears}")
        self.gear = gear
        if gear > 0:
            self.omega_roll = self.driveline.roller_omega(rpm, gear)

    @property
    def coupled(self) -> bool:
        return self.gear > 0

    def vehicle_speed_kmh(self) -> float:
        return self.omega_roll * self.config.roller_radius_m * MS_TO_KMH

    def load(
        self,
        *,
        rpm: float,
        brake_torque_nm: float,
        absorber_command_nm: float,
        dt: float,
        pedal_pct: float,
        fan_air_speed_m_s: float,
    ) -> DynoLoad:
        """``DynoLoad`` do tick (``rpm`` e ``brake_torque_nm`` do tick anterior)."""
        dl = self.driveline
        if self.coupled:
            omega = dl.roller_omega(rpm, self.gear)
            self.omega_roll = omega
            t_abs = self.absorber.step(absorber_command_nm, omega, dt)
            t_loss = self.loss_torque(omega)
            g = dl.overall_ratio(self.gear)
            load_nm = (t_abs + t_loss) * dl.k / g
            load_nm += (1.0 - dl.efficiency) * max(brake_torque_nm, 0.0)
            omega_crank = rpm * RPM_TO_RAD_S
            if dl.fixed_loss_kw > 0.0 and omega_crank > 1.0:
                load_nm += dl.fixed_loss_kw * 1000.0 / omega_crank
            inertia = dl.reflected_inertia(self.gear, self.roller_inertia)
            ratio = dl.wheel_to_crank_ratio(self.gear)
        else:
            omega = self.omega_roll
            t_abs = self.absorber.step(absorber_command_nm, omega, dt)
            t_loss = self.loss_torque(omega)
            decel = (t_abs + t_loss) / self.roller_inertia
            self.omega_roll = max(omega - decel * dt, 0.0)
            load_nm = 0.0
            inertia = 0.0
            ratio = 0.0
        self.last_absorber_nm = t_abs
        self.last_loss_nm = t_loss
        return DynoLoad.model_construct(
            reflected_inertia_kg_m2=inertia,
            load_torque_crank_nm=max(load_nm, 0.0),
            gear=self.gear,
            wheel_to_crank_ratio=ratio,
            pedal_pct=min(max(pedal_pct, 0.0), 100.0),
            fan_air_speed_m_s=max(fan_air_speed_m_s, 0.0),
            ambient=self.ambient,
            vehicle_speed_kmh=self.vehicle_speed_kmh(),
            clutch_pressed=False,
            launch_switch=False,
            shift_request=False,
            antilag_switch=False,
        )

    def after_step(self, rpm: float) -> float:
        """Velocidade do rolo depois do passo da física (acoplado: segue o motor)."""
        if self.coupled:
            self.omega_roll = self.driveline.roller_omega(rpm, self.gear)
        return self.omega_roll


@dataclass(frozen=True, slots=True)
class RollMeasurement:
    """Grandezas medidas pelo rolo num tick (W, N·m, rad/s)."""

    omega_roll: float
    alpha_roll: float
    absorber_nm: float
    loss_nm: float
    power_wheel_w: float
    torque_wheel_nm: float
    torque_engine_nm: float
    power_crank_w: float

    @property
    def power_wheel_kw(self) -> float:
        return self.power_wheel_w / 1000.0

    @property
    def whp(self) -> float:
        return self.power_wheel_kw / HP_KW


def measure_roll(
    *,
    roller_inertia_kg_m2: float,
    omega_roll: float,
    alpha_roll: float,
    absorber_nm: float,
    loss_nm: float,
    overall_ratio: float,
    k: float,
    efficiency: float,
) -> RollMeasurement:
    """Potência e torques pela inércia e aceleração do rolo (RF-05, RF-12)."""
    torque_roll = roller_inertia_kg_m2 * alpha_roll + absorber_nm + loss_nm
    power = torque_roll * omega_roll
    omega_wheel = omega_roll / k if k > 0.0 else 0.0
    torque_wheel = power / omega_wheel if omega_wheel > _MIN_OMEGA else 0.0
    torque_engine = torque_wheel / (overall_ratio * efficiency) if overall_ratio > 0.0 else 0.0
    return RollMeasurement(
        omega_roll=omega_roll,
        alpha_roll=alpha_roll,
        absorber_nm=absorber_nm,
        loss_nm=loss_nm,
        power_wheel_w=power,
        torque_wheel_nm=torque_wheel,
        torque_engine_nm=torque_engine,
        power_crank_w=power / efficiency,
    )


class AccelerationWindow[T]:
    """Diferença central de ``ω_roll`` sobre ``window`` ticks (ímpar), sem alocação.

    ``push`` devolve ``(α, item_central)`` quando a janela está cheia: o item central
    (amostra do tick ``k − (window − 1)/2``) fica alinhado com a aceleração estimada.
    """

    __slots__ = ("_count", "_dt", "_head", "_items", "_omegas", "window")

    def __init__(self, window: int, dt: float) -> None:
        if window < 3 or window % 2 == 0:  # noqa: PLR2004
            raise ValueError("window deve ser ímpar e ≥ 3")
        self.window = window
        self._dt = dt
        self._omegas = [0.0] * window
        self._items: list[T | None] = [None] * window
        self._head = 0
        self._count = 0

    def reset(self) -> None:
        self._head = 0
        self._count = 0
        self._items = [None] * self.window

    @property
    def ready(self) -> bool:
        return self._count >= self.window

    def push(self, omega: float, item: T) -> tuple[float, T] | None:
        w = self.window
        self._omegas[self._head] = omega
        self._items[self._head] = item
        self._head = (self._head + 1) % w
        self._count = min(self._count + 1, w)
        if self._count < w:
            return None
        oldest = self._head  # o mais antigo é o próximo a ser sobrescrito
        newest = (self._head - 1) % w
        center = (oldest + w // 2) % w
        alpha = (self._omegas[newest] - self._omegas[oldest]) / ((w - 1) * self._dt)
        return alpha, cast("T", self._items[center])
