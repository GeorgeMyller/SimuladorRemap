"""Controle de came variável (002 RF-11; D-06).

- Alvos de base: tabelas ``cam_intake_target``/``cam_exhaust_target`` (0 sem tabela);
- inibição a frio: com ``ect_c < min_ect_c`` os alvos são 0 (came estacionado);
- offsets ``intake_offset_deg``/``exhaust_offset_deg`` somados à tabela;
- limite de taxa ``max_rate_deg_s`` sobre o alvo comandado (parte do came estacionado).

Sem configuração habilitada a estratégia devolve as tabelas diretamente (RF-31 do
ecu-core preservado).
"""

from __future__ import annotations

from simremap.ecu.contracts import VvtConfig
from simremap.ecu.strategies.base import TickContext

__all__ = ["VvtControl"]


def _slew(current: float, target: float, step: float) -> float:
    return current + min(max(target - current, -step), step)


class VvtControl:
    __slots__ = ("cfg", "exhaust_deg", "intake_deg")

    def __init__(self, cfg: VvtConfig | None) -> None:
        self.cfg = cfg if cfg is not None else VvtConfig(enabled=False)
        self.intake_deg = 0.0
        self.exhaust_deg = 0.0

    def configure(self, cfg: VvtConfig | None) -> None:
        """Nova configuração (troca ``full``); a posição comandada continua."""
        self.cfg = cfg if cfg is not None else VvtConfig(enabled=False)

    def targets(self, ctx: TickContext, intake: float, exhaust: float) -> tuple[float, float]:
        """Alvos finais ``(admissão, escape)`` a partir dos valores das tabelas."""
        c = self.cfg
        if not c.enabled:
            self.intake_deg, self.exhaust_deg = intake, exhaust
            return intake, exhaust
        if ctx.ect_c < c.min_ect_c:
            intake = exhaust = 0.0
        else:
            intake += c.intake_offset_deg
            exhaust += c.exhaust_offset_deg
        step = c.max_rate_deg_s * ctx.dt
        self.intake_deg = _slew(self.intake_deg, intake, step)
        self.exhaust_deg = _slew(self.exhaust_deg, exhaust, step)
        return self.intake_deg, self.exhaust_deg
