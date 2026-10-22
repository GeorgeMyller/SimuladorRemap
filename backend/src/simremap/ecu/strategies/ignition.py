"""Avanço por cilindro e knock control (ecu-core RF-11, RF-13; D-20, D-BUS-05).

Avanço normal do cilindro ``k``:
``base(rpm, carga) + trim_k + corr_IAT + corr_ECT − retardo_knock_k``, com clamp em
−20..60 °BTDC. Em arranque (RPM < ``cranking_rpm``) vale ``cranking_ign_deg``.

Knock control (por cilindro, sobre ``SensorReadings.knock_intensity`` 0–1):

- evento = ``knock_intensity_k > knock_threshold(rpm)`` com RPM ≥ ``rpm_min`` e MAP ≥
  ``map_min_kpa``; a intensidade é a do último ciclo, por isso conta-se no máximo um
  evento por ciclo do motor (``120 / rpm`` s) e por cilindro;
- cada evento soma ``retard_step_deg`` até ``max_retard_deg`` e emite ``knock_retard``;
- após ``recovery_hold_s`` sem eventos, o retardo cai ``recovery_deg_per_s``;
- com algum cilindro no retardo máximo por ``max_retard_hold_s``, o teto de boost cai
  ``boost_reduction_kpa_at_max``;
- ``open_loop`` (sondas, ``ProbeOverrides.knock_control_open_loop``) fixa o retardo em 0.
"""

from __future__ import annotations

from math import inf

from simremap.ecu.compiled import CompiledCalibration
from simremap.ecu.contracts import KnockControlConfig, TableKind
from simremap.ecu.limits import DEFAULT_KNOCK_THRESHOLD, IGNITION_MAX_DEG, IGNITION_MIN_DEG
from simremap.ecu.strategies.base import TickContext

__all__ = ["Ignition", "KnockControl"]

_K = TableKind


class KnockControl:
    __slots__ = (
        "at_max_since",
        "boost_reduction",
        "enabled",
        "hold_s",
        "last_event_t",
        "map_min",
        "max_hold_s",
        "max_retard",
        "n_cyl",
        "next_eligible_t",
        "open_loop",
        "recovery",
        "retard",
        "rpm_min",
        "step",
    )

    def __init__(self, cfg: KnockControlConfig | None, n_cyl: int) -> None:
        self.n_cyl = n_cyl
        self.retard = [0.0] * n_cyl
        self.last_event_t = [-inf] * n_cyl
        self.next_eligible_t = [-inf] * n_cyl
        self.at_max_since = inf
        self.open_loop = False
        self.configure(cfg)

    def configure(self, cfg: KnockControlConfig | None) -> None:
        c = cfg if cfg is not None else KnockControlConfig(enabled=False)
        self.enabled = c.enabled
        self.step = c.retard_step_deg
        self.max_retard = c.max_retard_deg
        self.hold_s = c.recovery_hold_s
        self.recovery = c.recovery_deg_per_s
        self.rpm_min = c.rpm_min
        self.map_min = c.map_min_kpa
        self.boost_reduction = c.boost_reduction_kpa_at_max
        self.max_hold_s = c.max_retard_hold_s

    def update(self, ctx: TickContext, threshold: float) -> None:
        retard = self.retard
        if self.open_loop or not self.enabled:
            for k in range(self.n_cyl):
                retard[k] = 0.0
            self.at_max_since = inf
            return
        t = ctx.t
        rpm = ctx.rpm
        armed = rpm >= self.rpm_min and ctx.map_kpa >= self.map_min
        cycle_s = 120.0 / rpm if rpm > 0.0 else inf
        knock = ctx.knock_intensity
        any_at_max = False
        for k in range(self.n_cyl):
            r = retard[k]
            if armed and knock[k] > threshold and t >= self.next_eligible_t[k]:
                self.next_eligible_t[k] = t + cycle_s
                self.last_event_t[k] = t
                r = min(r + self.step, self.max_retard)
                ctx.emit("knock_retard", cylinder=k + 1, value=r, detail=f"{knock[k]:.3f}")
            elif r > 0.0 and t - self.last_event_t[k] >= self.hold_s:
                r -= self.recovery * ctx.dt
                r = max(r, 0.0)
            retard[k] = r
            if r >= self.max_retard:
                any_at_max = True
        if any_at_max:
            if self.at_max_since == inf:
                self.at_max_since = t
        else:
            self.at_max_since = inf

    def boost_ceiling_reduction(self, t: float) -> float:
        """kPa a descontar do alvo de boost (retardo máximo mantido)."""
        if self.at_max_since != inf and t - self.at_max_since >= self.max_hold_s:
            return self.boost_reduction
        return 0.0

    @property
    def any_retard(self) -> bool:
        return any(r > 0.0 for r in self.retard)


class Ignition:
    """Avanço normal por cilindro (com knock), antes dos overrides da arbitragem."""

    __slots__ = ("adv", "knock", "n_cyl", "tables")

    def __init__(self, compiled: CompiledCalibration, knock: KnockControl) -> None:
        self.tables = compiled
        self.knock = knock
        self.n_cyl = compiled.n_cyl
        self.adv = [0.0] * compiled.n_cyl

    def set_compiled(self, compiled: CompiledCalibration) -> None:
        self.tables = compiled

    def threshold(self, ctx: TickContext) -> float:
        table = self.tables.tables.get(_K.KNOCK_THRESHOLD)
        return table.at(ctx.inputs) if table is not None else DEFAULT_KNOCK_THRESHOLD

    def compute(self, ctx: TickContext, cranking: bool) -> None:
        cal = self.tables
        adv = self.adv
        if cranking:
            for k in range(self.n_cyl):
                adv[k] = cal.cranking_ign_deg
            ctx.adv_ref = cal.cranking_ign_deg
            return
        inputs = ctx.inputs
        tables = cal.tables
        base_t = tables.get(_K.IGNITION_BASE)
        base = base_t.at(inputs) if base_t is not None else 10.0
        iat_t = tables.get(_K.IGN_CORR_IAT)
        ect_t = tables.get(_K.IGN_CORR_ECT)
        if iat_t is not None:
            base += iat_t.at(inputs)
        if ect_t is not None:
            base += ect_t.at(inputs)
        trims = cal.ign_trim_cyl
        retard = self.knock.retard
        total = 0.0
        for k in range(self.n_cyl):
            tt = trims[k]
            a = base - retard[k] if tt is None else base + tt.at(inputs) - retard[k]
            if a < IGNITION_MIN_DEG:
                a = IGNITION_MIN_DEG
            elif a > IGNITION_MAX_DEG:
                a = IGNITION_MAX_DEG
            adv[k] = a
            total += a
        ctx.adv_ref = total / self.n_cyl
