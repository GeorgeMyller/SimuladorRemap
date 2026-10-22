"""Controladores da bancada: PID de RPM no absorvedor, PID de carga no pedal e rampa (RF-07, RF-08).

- PID genérico ``u = Kp·e + Ki·∫e dt + Kd·de/dt`` com anti-windup por *clamping*: o
  integrador congela quando a saída satura e o erro empurra para fora da faixa.
- PID de RPM: ``e = rpm_meas − rpm_ref``; ganhos ``DynoRigConfig.rpm_pid`` (padrão
  2,0 N·m/rpm, 4,0 N·m/(rpm·s), 0,02 N·m·s/rpm). Decisão de interpretação: a saída do
  PID é torque de carga **referido ao virabrequim** (a rotação do erro também é a do
  virabrequim), convertido para o absorvedor por ``G / k``. Com os ganhos no rolo o laço
  ficaria com polo em ~0,4 s⁻¹ e oscilaria por vários segundos em 4.ª marcha.
  Pré-alimentação (*feedforward*): ``η·T_brake`` do tick anterior (célula de carga virtual)
  menos o torque inercial da rampa ``J_total · α_ref``; o PID corrige só o resíduo.
- PID de carga (só ``steady_state_hold``): alvo de ``map_kpa`` com saída de pedal 0..100 %,
  ganhos ``DynoRigConfig.load_pid`` (0,5 %/kPa, 2,0 %/(kPa·s)); alvo ``pedal_pct`` fixo
  dispensa o PID.
- Rampa: ``rpm_ref(t) = start_rpm + rate · (t − t_running)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from simremap.dyno.rig import RPM_TO_RAD_S, Driveline

__all__ = ["LoadController", "Pid", "Ramp", "RpmController"]


class Pid:
    """PID de tempo discreto com anti-windup por *clamping* e derivada da medida."""

    __slots__ = ("integral", "kd", "ki", "kp", "out_max", "out_min", "prev_error", "primed")

    def __init__(self, gains: tuple[float, float, float], out_min: float, out_max: float) -> None:
        if out_max < out_min:
            raise ValueError("out_max deve ser ≥ out_min")
        self.kp, self.ki, self.kd = gains
        self.out_min = out_min
        self.out_max = out_max
        self.integral = 0.0
        self.prev_error = 0.0
        self.primed = False

    def reset(self) -> None:
        self.integral = 0.0
        self.prev_error = 0.0
        self.primed = False

    def update(
        self,
        error: float,
        dt: float,
        *,
        bias: float = 0.0,
        out_min: float | None = None,
        out_max: float | None = None,
    ) -> float:
        """Saída limitada de ``bias + Kp·e + Ki·∫e + Kd·de/dt``."""
        low = self.out_min if out_min is None else out_min
        high = self.out_max if out_max is None else out_max
        derivative = (error - self.prev_error) / dt if self.primed else 0.0
        self.prev_error = error
        self.primed = True
        candidate = self.integral + error * dt
        raw = bias + self.kp * error + self.ki * candidate + self.kd * derivative
        if raw > high:
            if error < 0.0:
                self.integral = candidate
            return high
        if raw < low:
            if error > 0.0:
                self.integral = candidate
            return low
        self.integral = candidate
        return raw


@dataclass(frozen=True, slots=True)
class Ramp:
    """Referência ``rpm_ref(t) = start_rpm + rate · (t − t0)``, limitada a ``end_rpm``."""

    start_rpm: float
    rate_rpm_s: float
    t0_s: float
    end_rpm: float

    def at(self, t_sim_s: float) -> float:
        return min(self.start_rpm + self.rate_rpm_s * max(t_sim_s - self.t0_s, 0.0), self.end_rpm)


class RpmController:
    """PID de RPM no absorvedor com pré-alimentação; devolve ``T_cmd`` no rolo (N·m)."""

    __slots__ = ("driveline", "pid", "roller_inertia")

    def __init__(
        self, gains: tuple[float, float, float], driveline: Driveline, roller_inertia: float
    ) -> None:
        self.pid = Pid(gains, -1e9, 1e9)
        self.driveline = driveline
        self.roller_inertia = roller_inertia

    def reset(self) -> None:
        self.pid.reset()

    def command(
        self,
        *,
        rpm: float,
        rpm_ref: float,
        ref_rate_rpm_s: float,
        gear: int,
        brake_torque_nm: float,
        engine_inertia_kg_m2: float,
        loss_nm: float,
        capacity_nm: float,
        dt: float,
    ) -> float:
        """Torque pedido ao absorvedor (no rolo), em 0..``capacity_nm``."""
        dl = self.driveline
        g = dl.overall_ratio(gear)
        if g <= 0.0:
            self.pid.reset()
            return 0.0
        to_roll = g / dl.k  # N·m no virabrequim → N·m no rolo
        j_total = engine_inertia_kg_m2 + dl.reflected_inertia(gear, self.roller_inertia)
        alpha_ref = ref_rate_rpm_s * RPM_TO_RAD_S
        feedforward = dl.efficiency * max(brake_torque_nm, 0.0) - j_total * alpha_ref
        # Carga no virabrequim vinda do rolo: L = (T_abs + T_loss) / to_roll, com
        # T_abs ∈ 0..capacidade ⇒ L ∈ [T_loss / to_roll, (cap + T_loss) / to_roll].
        crank_load = self.pid.update(
            rpm - rpm_ref,
            dt,
            bias=feedforward,
            out_min=loss_nm / to_roll,
            out_max=(capacity_nm + loss_nm) / to_roll,
        )
        return min(max(crank_load * to_roll - loss_nm, 0.0), capacity_nm)


class LoadController:
    """Carga da célula: pedal fixo ou PID de MAP (saída 0..100 %)."""

    __slots__ = ("pid",)

    def __init__(self, gains: tuple[float, float, float]) -> None:
        self.pid = Pid(gains, 0.0, 100.0)

    def reset(self) -> None:
        self.pid.reset()

    def pedal(
        self,
        *,
        map_kpa: float,
        map_target_kpa: float | None,
        pedal_target_pct: float | None,
        dt: float,
    ) -> float:
        if map_target_kpa is None:
            return min(max(pedal_target_pct or 0.0, 0.0), 100.0)
        return self.pid.update(map_target_kpa - map_kpa, dt)
