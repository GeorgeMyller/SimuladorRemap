"""Falhas físicas injetáveis dos cenários (RF-23).

``fuel_pump_weak`` limita a vazão de combustível (a pressão de rail cai quando a vazão
pedida excede o teto), ``injector_clogged`` reduz a vazão de um bico, ``boost_leak`` abre
um orifício do volume de boost (ou do coletor, sem sobrealimentação) para o ambiente,
``sensor_bias`` soma um viés a um canal de ``SensorReadings`` e ``wastegate_stuck`` fixa a
abertura da wastegate ignorando ``wastegate_duty_pct``. Cada falha vale a partir de
``start_t_sim_s``.
"""

from __future__ import annotations

from collections.abc import Sequence

from simremap.physics.contracts import PhysicsFault

__all__ = ["CD_LEAK", "ActiveFaults"]

CD_LEAK = 0.7


class ActiveFaults:
    """Consulta das falhas ativas num instante simulado (sem estado próprio)."""

    __slots__ = ("_faults", "n_cyl")

    def __init__(self, faults: Sequence[PhysicsFault], n_cyl: int) -> None:
        self._faults = tuple(faults)
        self.n_cyl = n_cyl

    def __bool__(self) -> bool:
        return bool(self._faults)

    def _active(self, kind: str, t_sim_s: float) -> list[PhysicsFault]:
        return [f for f in self._faults if f.kind == kind and t_sim_s >= f.start_t_sim_s]

    def fuel_pump_max_lph(self, t_sim_s: float) -> float | None:
        """Teto de vazão da bomba (L/h), o mais restritivo entre as falhas ativas."""
        caps = [f.fuel_pump_max_lph for f in self._active("fuel_pump_weak", t_sim_s)]
        values = [c for c in caps if c is not None]
        return min(values) if values else None

    def injector_factors(self, t_sim_s: float) -> list[float]:
        """Fator de vazão por cilindro (1,0 = bico limpo)."""
        factors = [1.0] * self.n_cyl
        for f in self._active("injector_clogged", t_sim_s):
            if f.cylinder is not None and f.injector_flow_factor is not None:
                factors[f.cylinder - 1] *= f.injector_flow_factor
        return factors

    def leak_cd_area_m2(self, t_sim_s: float) -> float:
        """``C_d · A`` total das fugas de boost (m²)."""
        total = 0.0
        for f in self._active("boost_leak", t_sim_s):
            if f.leak_area_mm2 is not None:
                total += f.leak_area_mm2 * 1e-6
        return CD_LEAK * total

    def sensor_bias(self, t_sim_s: float) -> dict[str, float]:
        """Viés por canal de ``SensorReadings`` (soma das falhas ativas)."""
        out: dict[str, float] = {}
        for f in self._active("sensor_bias", t_sim_s):
            if f.sensor_channel is not None and f.sensor_bias is not None:
                out[f.sensor_channel] = out.get(f.sensor_channel, 0.0) + f.sensor_bias
        return out

    def wastegate_stuck_fraction(self, t_sim_s: float) -> float | None:
        """Abertura fixa da wastegate (0..1) ou ``None`` sem falha ativa."""
        active = self._active("wastegate_stuck", t_sim_s)
        if not active:
            return None
        pct = active[-1].stuck_position_pct
        return None if pct is None else pct / 100.0
