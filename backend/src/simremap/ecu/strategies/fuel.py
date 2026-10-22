"""Combustível: modos, lambda alvo, compensações, trims por cilindro e pulso.

Fontes: ecu-core RF-06 a RF-08, RF-12.

Equações (Apêndice B):

- ``V_cyl = displacement_cc / n_cyl · 1e−6`` (m³); ``R = 287,05 J/(kg·K)``;
- ``T_charge = IAT_K + k·(ECT_K − IAT_K)`` com ``k = charge_temp_blend``;
- ``m_air = (VE/100) · MAP_kPa · 1000 · V_cyl / (R · T_charge)`` (kg → g por cilindro/ciclo);
- ``m_fuel = m_air / (λ_alvo · AFR_st)``;
- ``m_fuel_corr = m_fuel · (1 + STFT + LTFT) · (1 + c_ECT) · (1 + c_IAT)
  · (1 + c_accel + c_afterstart) · (1 + trim_cyl)``;
- ``q_inj = flow · ρ / 60000 · sqrt(ΔP_real / ΔP_ref)`` (g/ms);
- ``PW = m_fuel_corr / q_inj + t_dead(V_bat)``;
- duty ``= PW / (120000 / rpm) · 100``.

O cálculo divide-se em ``prepare`` (passos 3–4 do pipeline: massa de ar, lambda base,
compensações) e ``pulse`` (passo 8, com o lambda final da arbitragem).
"""

from __future__ import annotations

from math import exp, isfinite, sqrt

from simremap.ecu.compiled import (
    QUANTITY_INDEX,
    CompiledCalibration,
    CompiledTable,
    EcuHardwareConfig,
)
from simremap.ecu.contracts import AxisQuantity, TableKind
from simremap.ecu.limits import R_AIR_J_KG_K
from simremap.ecu.strategies.base import TickContext

__all__ = ["FuelStrategy", "speed_density_air_g"]

_K = TableKind
_TPS_RATE = QUANTITY_INDEX[AxisQuantity.TPS_RATE_PCT_S]
_KELVIN = 273.15
_DEFAULT_VE_PCT = 100.0  # enchimento teórico quando não há tabela ve (profile_air_model)


def speed_density_air_g(  # noqa: PLR0917 - variáveis da equação do Apêndice B
    ve_pct: float, map_kpa: float, v_cyl_m3: float, iat_c: float, ect_c: float, blend: float
) -> float:
    """Massa de ar por cilindro e ciclo (g) pelo speed-density."""
    iat_k = iat_c + _KELVIN
    t_charge = iat_k + blend * (ect_c + _KELVIN - iat_k)
    return ve_pct / 100.0 * map_kpa * 1000.0 * v_cyl_m3 / (R_AIR_J_KG_K * t_charge) * 1000.0


class FuelStrategy:
    """Estado e cálculo do combustível de um runtime."""

    __slots__ = (
        "_decay_dt",
        "_decay_factor",
        "accel_enrich",
        "afterstart_initial",
        "air_g",
        "corr_common",
        "cranking",
        "cranking_pw_ms",
        "cyl_factor",
        "dead_time_ms",
        "direct_pw_ms",
        "hw",
        "lambda_base",
        "n_cyl",
        "q_inj_g_ms",
        "running",
        "start_t",
        "t_since_start",
        "tables",
    )

    def __init__(self, compiled: CompiledCalibration, hw: EcuHardwareConfig) -> None:
        self.hw = hw
        self.n_cyl = hw.n_cyl
        self.tables = compiled
        self.cyl_factor = [1.0] * hw.n_cyl
        self.accel_enrich = 0.0
        self.afterstart_initial = 0.0
        self.running = False
        self.start_t = 0.0
        self.t_since_start = 0.0
        self.air_g = 0.0
        self.corr_common = 1.0
        self.cranking = False
        self.cranking_pw_ms = 0.0
        self.direct_pw_ms = 0.0
        self.lambda_base = 1.0
        self.q_inj_g_ms = hw.q_inj_ref_g_ms
        self.dead_time_ms = 0.0
        self._decay_dt = -1.0
        self._decay_factor = 1.0

    def set_compiled(self, compiled: CompiledCalibration) -> None:
        self.tables = compiled

    def reset_session(self) -> None:
        self.accel_enrich = 0.0
        self.running = False
        self.t_since_start = 0.0
        self.afterstart_initial = 0.0

    def _decay(self, dt: float, tau: float) -> float:
        key = dt / tau
        if key != self._decay_dt:
            self._decay_dt = key
            self._decay_factor = exp(-key)
        return self._decay_factor

    def prepare(  # noqa: PLR0912, PLR0915 - passos 3 e 4 do Apêndice D (hot path)
        self, ctx: TickContext, air_mg_from_hook: float | None
    ) -> None:
        """Passos 3 e 4: massa de ar, lambda base, compensações e trims por cilindro."""
        cal = self.tables
        tables = cal.tables
        inputs = ctx.inputs
        hw = self.hw
        rpm = ctx.rpm

        # Arranque e pós-partida (RF-08).
        self.cranking = 0.0 < rpm < cal.cranking_rpm
        if rpm >= cal.cranking_rpm:
            if not self.running:
                self.running = True
                self.start_t = ctx.t
                after_t = tables.get(_K.AFTERSTART_ENRICH)
                self.afterstart_initial = after_t.at(inputs) / 100.0 if after_t is not None else 0.0
            self.t_since_start = ctx.t - self.start_t
        else:
            self.running = False
            self.t_since_start = 0.0
        crank_table = tables.get(_K.CRANKING_FUEL)
        self.cranking_pw_ms = crank_table.at(inputs) if crank_table is not None else 0.0

        # Lambda alvo base.
        lam_table = tables.get(_K.LAMBDA_TARGET)
        self.lambda_base = lam_table.at(inputs) if lam_table is not None else 1.0
        ctx.lambda_target_base = self.lambda_base

        # Massa de ar (modo do fuel_model).
        mode = cal.fuel_mode
        if mode == "direct_pulse_ms":
            base = tables.get(_K.INJ_BASE_MS)
            self.direct_pw_ms = base.at(inputs) if base is not None else 0.0
            self.air_g = 0.0
        else:
            air_g = -1.0
            if mode == "profile_air_model" and air_mg_from_hook is not None:
                air_g = air_mg_from_hook / 1000.0 if isfinite(air_mg_from_hook) else 0.0
            if air_g < 0.0:
                ve = tables.get(_K.VE)
                ve_pct = ve.at(inputs) if ve is not None else _DEFAULT_VE_PCT
                air_g = speed_density_air_g(
                    ve_pct, ctx.map_kpa, hw.v_cyl_m3, ctx.iat_c, ctx.ect_c, cal.charge_temp_blend
                )
            self.air_g = air_g

        # Compensações ECT/IAT, aceleração (com decaimento τ) e pós-partida.
        c_ect = _pct(tables.get(_K.FUEL_CORR_ECT), inputs)
        c_iat = _pct(tables.get(_K.FUEL_CORR_IAT), inputs)
        accel = self.accel_enrich * self._decay(ctx.dt, cal.accel_enrich_tau_s)
        if ctx.tps_rate_pct_s > 0.0:
            table = tables.get(_K.ACCEL_ENRICH)
            if table is not None:
                inputs[_TPS_RATE] = ctx.tps_rate_pct_s
                target = table.at(inputs) / 100.0
                accel = max(accel, target)
        self.accel_enrich = accel
        after = 0.0
        if self.running and self.afterstart_initial > 0.0:
            frac = 1.0 - self.t_since_start / cal.afterstart_decay_s
            if frac > 0.0:
                after = self.afterstart_initial * frac
        self.corr_common = (1.0 + c_ect) * (1.0 + c_iat) * (1.0 + accel + after)

        # Trims por cilindro (RF-12).
        trims = cal.fuel_trim_cyl
        factors = self.cyl_factor
        for k in range(self.n_cyl):
            tt = trims[k]
            factors[k] = 1.0 + tt.at(inputs) / 100.0 if tt is not None else 1.0

        # Vazão do bico e dead time.
        q = hw.q_inj_ref_g_ms
        dp = ctx.fuel_pressure_kpa
        if hw.use_rail_pressure and dp > 0.0 and isfinite(dp):
            q *= sqrt(dp / hw.ref_pressure_kpa)
        self.q_inj_g_ms = q
        dead = tables.get(_K.INJ_DEAD_TIME)
        self.dead_time_ms = dead.at(inputs) if dead is not None else hw.dead_time(ctx.battery_v)

    def pulse(self, k: int, lambda_final: float, trim_total: float) -> tuple[float, float]:
        """Passo 8: massa de combustível (mg) e pulso (ms) do cilindro ``k``."""
        if self.cranking:
            pw = self.cranking_pw_ms
            return max(pw - self.dead_time_ms, 0.0) * self.q_inj_g_ms * 1000.0, pw
        factor = (1.0 + trim_total) * self.corr_common * self.cyl_factor[k]
        if self.tables.fuel_mode == "direct_pulse_ms":
            inj_ms = self.direct_pw_ms * factor * (self.lambda_base / lambda_final)
            if inj_ms <= 0.0:
                return 0.0, 0.0
            return inj_ms * self.q_inj_g_ms * 1000.0, inj_ms + self.dead_time_ms
        m_fuel_g = self.air_g / (lambda_final * self.hw.afr_stoich) * factor
        if m_fuel_g <= 0.0:
            return 0.0, 0.0
        return m_fuel_g * 1000.0, m_fuel_g / self.q_inj_g_ms + self.dead_time_ms


def _pct(table: CompiledTable | None, inputs: list[float]) -> float:
    return table.at(inputs) / 100.0 if table is not None else 0.0
