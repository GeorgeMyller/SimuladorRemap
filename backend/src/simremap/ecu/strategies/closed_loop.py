"""Malha fechada wideband PI com anti-windup e LTFT por célula (ecu-core RF-09, RF-10; OQ-05).

- ``e = (λ_medido − λ_alvo) / λ_alvo`` (positivo = pobre ⇒ trim positivo);
- ``STFT = clamp(kp·e + I, ±trim_limit)``; ``I += ki·e·dt`` só quando
  ``|kp·e + I| < trim_limit`` (integração condicional);
- ativação: estratégia ligada, ECT ≥ ``min_ect_c``, RPM em ``[rpm_min, rpm_max]``,
  MAP ≤ ``map_max_kpa``, tempo após partida ≥ ``delay_after_start_s`` e sensor válido.
  Fora disso o trim é 0 e o integrador reinicia (EC-05). Com corte de combustível no
  tick anterior o trim fica congelado (a sonda lê ar puro);
- LTFT (opcional): grade 8×8 RPM × MAP; a célula ativa absorve o STFT a
  ``ltft_rate_pct_s`` (o integrador perde o mesmo valor, o total mantém-se), limitada a
  ``±ltft_limit_pct``. Reinicia a cada sessão (premissa OQ-05): vive só no runtime.
"""

from __future__ import annotations

from simremap.ecu.contracts import ClosedLoopConfig
from simremap.ecu.limits import LTFT_GRID_SIZE
from simremap.ecu.strategies.base import TickContext

__all__ = ["ClosedLoop"]


class ClosedLoop:
    __slots__ = (
        "_at_limit",
        "active",
        "cell",
        "delay_s",
        "enabled",
        "integ",
        "ki",
        "kp",
        "limit",
        "ltft",
        "ltft_enabled",
        "ltft_limit",
        "ltft_rate",
        "map_max",
        "min_ect",
        "rpm_max",
        "rpm_min",
        "stft",
    )

    def __init__(self, cfg: ClosedLoopConfig | None) -> None:
        self.ltft = [0.0] * (LTFT_GRID_SIZE * LTFT_GRID_SIZE)
        self.configure(cfg)
        self.reset_session()

    def configure(self, cfg: ClosedLoopConfig | None) -> None:
        c = cfg if cfg is not None else ClosedLoopConfig(enabled=False)
        self.enabled = c.enabled
        self.kp = c.kp
        self.ki = c.ki_per_s
        self.limit = c.trim_limit_pct / 100.0
        self.min_ect = c.min_ect_c
        self.rpm_min = c.rpm_min
        self.rpm_max = c.rpm_max
        self.map_max = c.map_max_kpa
        self.delay_s = c.delay_after_start_s
        self.ltft_enabled = c.ltft_enabled
        self.ltft_rate = c.ltft_rate_pct_s / 100.0
        self.ltft_limit = c.ltft_limit_pct / 100.0

    def reset_session(self) -> None:
        self.stft = 0.0
        self.integ = 0.0
        self.active = False
        self._at_limit = False
        self.cell = 0
        for i in range(len(self.ltft)):
            self.ltft[i] = 0.0

    def _cell(self, rpm: float, map_kpa: float) -> int:
        n = LTFT_GRID_SIZE
        i = int((rpm - self.rpm_min) / (self.rpm_max - self.rpm_min) * n)
        j = int(map_kpa / self.map_max * n)
        i = 0 if i < 0 else (n - 1 if i >= n else i)
        j = 0 if j < 0 else (n - 1 if j >= n else j)
        return j * n + i

    @property
    def ltft_value(self) -> float:
        return self.ltft[self.cell] if self.ltft_enabled else 0.0

    @property
    def trim_total(self) -> float:
        """Fração aplicada ao combustível: ``STFT + LTFT``."""
        return self.stft + self.ltft_value

    def update(self, ctx: TickContext, t_since_start: float) -> None:
        rpm = ctx.rpm
        self.cell = self._cell(rpm, ctx.map_kpa)
        ok = (
            self.enabled
            and ctx.lambda_valid
            and ctx.ect_c >= self.min_ect
            and self.rpm_min <= rpm <= self.rpm_max
            and ctx.map_kpa <= self.map_max
            and t_since_start >= self.delay_s
        )
        if not ok:
            self.active = False
            self.stft = 0.0
            self.integ = 0.0
            self._at_limit = False
            return
        if ctx.fuel_cut_prev:
            self.active = False  # trim congelado durante o corte
            return
        self.active = True
        target = ctx.lambda_target_prev
        e = (ctx.lambda_measured - target) / target
        limit = self.limit
        p = self.kp * e
        u = p + self.integ
        if -limit < u < limit:
            self.integ += self.ki * e * ctx.dt
            u = p + self.integ
        at_limit = not -limit < u < limit
        if u > limit:
            u = limit
        elif u < -limit:
            u = -limit
        self.stft = u
        if at_limit and not self._at_limit:
            ctx.emit("closed_loop_limit", value=u * 100.0, detail="stft no limite")
        self._at_limit = at_limit
        if self.ltft_enabled and self.stft != 0.0:
            cell = self.cell
            step = self.ltft_rate * ctx.dt
            move = self.stft if -step <= self.stft <= step else (step if self.stft > 0 else -step)
            new = self.ltft[cell] + move
            lim = self.ltft_limit
            if new > lim:
                new = lim
            elif new < -lim:
                new = -lim
            moved = new - self.ltft[cell]
            self.ltft[cell] = new
            self.integ -= moved
            self.stft -= moved
