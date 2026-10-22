"""Configuração versionada do modelo de dano (knock-and-failure-model seção 9, RF-11 a RF-17).

Os coeficientes vivem neste arquivo: reverter um coeficiente é reverter o arquivo
(data-model 5.3). Toda mudança de valor padrão exige subir ``DAMAGE_CONFIG_VERSION``,
porque o ``damage_digest`` e os laudos dependem destes números.

``DAMAGE_FEATURES`` controla a entrega incremental do Sprint 2:
``knock`` → ``signal`` → ``thermal`` → ``mechanical`` → ``preignition`` → ``forensic`` →
``spectrum`` → ``damage_off``.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from simremap.catalog.contracts import FLEX_FUEL_ID, FUEL_IDS
from simremap.core.contracts import ContractModel
from simremap.physics.contracts import MAX_CYLINDERS
from simremap.physics.fuel_blend import ETHANOL_PCT_MAX, ETHANOL_PCT_MIN, blend_weight

__all__ = [
    "DAMAGE_CONFIG_VERSION",
    "DAMAGE_FEATURES",
    "DEFAULT_DAMAGE_CONFIG",
    "DamageConfig",
    "DamageFeature",
]

DAMAGE_CONFIG_VERSION: Final = "1.2.0"

DamageFeature = Literal[
    "knock", "signal", "thermal", "mechanical", "preignition", "forensic", "spectrum", "damage_off"
]
DAMAGE_FEATURES: Final[tuple[DamageFeature, ...]] = (
    "knock",
    "signal",
    "thermal",
    "mechanical",
    "preignition",
    "forensic",
    "spectrum",
    "damage_off",
)
"""Ordem de entrega das capacidades do modelo de dano."""

END_CYLINDER_GAIN: Final = 0.85
CENTER_CYLINDER_GAIN: Final = 1.0


def _default_preignition_thresholds() -> dict[str, float]:
    # °C de superfície do ponto quente por combustível (OQ-02 + 20 °C; calibrado em T295
    # contra ``hot_spot_temp_c`` da física): o ponto quente de série mais quente em carga
    # (MAP ≥ 150 kPa) é 748 °C (coupé E27, 3.ª puxada de um multi_pull) e fica 32 °C abaixo
    # da janela ativa (T_thr − 60 = 780 °C); a ordem entre combustíveis do OQ-02 é mantida
    return {"e27": 840.0, "e0": 820.0, "podium": 880.0, "e100": 860.0}


class DamageConfig(ContractModel):
    """Coeficientes do modelo de dano. Padrões = valores das RFs da spec."""

    config_version: str = Field(DAMAGE_CONFIG_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    features: tuple[DamageFeature, ...] = DAMAGE_FEATURES
    # --- knock: MAPO, janela do sensor e ruído (RF-05)
    c_mapo: float = Field(0.5, gt=0.0, le=2.0)  # (-)
    xb_end: float = Field(0.98, ge=0.9, le=0.999)  # fração queimada de fim de combustão
    knock_window_start_deg_atdc: float = Field(-5.0, ge=-30.0, le=30.0)  # ° ATDC
    knock_window_end_deg_atdc: float = Field(60.0, ge=10.0, le=90.0)  # ° ATDC
    knock_sensor_gain: list[Annotated[float, Field(gt=0.0, le=2.0)]] | None = None
    knock_noise_sigma: float = Field(0.25, ge=0.0, le=1.0)  # bar
    combustion_efficiency: float = Field(0.98, gt=0.5, le=1.0)  # η_c de Q_disp (Apêndice A)
    # × A de Douaud-Eyzat (17,68 ms → 75,1 ms; 1.2.0): calibrado no laço físico + ECU de série
    # (integral de Livengood-Wu ≤ 0,83 nos 4 veículos de série); τ ≈ 3,1 ms a 60 atm, 900 K e
    # ON 88, dentro dos atrasos medidos em máquina de compressão rápida para gasolinas
    knock_tau_multiplier: float = Field(4.25, gt=0.0, le=10.0)
    tau_saturation_ms: float = Field(1.0e6, gt=0.0)  # τ saturado (EC-03)
    tau_min_temp_k: float = Field(400.0, gt=0.0)  # K abaixo do qual τ satura (EC-03)
    tau_min_pressure_kpa: float = Field(50.0, gt=0.0)  # kPa abaixo do qual τ satura (EC-03)
    knock_noise_floor_base: float = Field(0.05, ge=0.0)  # b(rpm) = base + slope·(rpm/ref)²
    knock_noise_floor_slope: float = Field(0.10, ge=0.0)
    knock_noise_floor_rpm_ref: float = Field(7000.0, gt=0.0)  # rev/min
    knock_event_min_interval_s: float = Field(0.1, gt=0.0)  # 10 event.knock/s por cilindro
    # --- dano por knock (RF-11)
    i_safe: float = Field(1.0, ge=0.0)  # bar de MAPO
    c_knock: float = Field(1.5e-4, ge=0.0)  # c_k (-)
    knock_energy_ref_j: float = Field(100.0, gt=0.0)  # J (divisor de E_k)
    head_gasket_knock_share: float = Field(0.30, ge=0.0, le=1.0)  # fração do dano do pistão
    knock_temp_gain_c: float = Field(25.0, ge=0.0)  # °C por unidade de I acima de 1
    knock_temp_tau_s: float = Field(1.5, gt=0.0)  # s
    # --- lambda pobre em carga (RF-13)
    k_lean_c: float = Field(600.0, ge=0.0)  # °C
    lambda_lean_ref: float = Field(0.88, ge=0.7, le=1.0)  # (-)
    lean_map_min_kpa: float = Field(150.0, ge=100.0)  # kPa abs
    # --- térmico por Larson-Miller e Robinson (RF-12)
    lm_constant: float = Field(20.0, gt=0.0)  # C (-)
    piston_t_ref_s: float = Field(300.0, gt=0.0)  # s
    valve_t_ref_s: float = Field(180.0, gt=0.0)  # s
    turbine_t_ref_s: float = Field(120.0, gt=0.0)  # s
    valve_egt_margin_c: float = Field(50.0, ge=0.0)  # °C acima de egt_limit_c
    # τ térmico do metal (1.2.0): a fluência usa a temperatura de metal de 1ª ordem e não o
    # pico instantâneo da EGT de gás (cabeça da válvula de escape ≈ 2–5 s; roda da turbina
    # e carcaça ≈ 5–10 s, mais massiva)
    valve_thermal_tau_s: float = Field(5.0, gt=0.0, le=60.0)  # s
    turbine_thermal_tau_s: float = Field(6.0, gt=0.0, le=120.0)  # s
    # --- biela (RF-14)
    rod_instant_ratio: float = Field(1.30, gt=1.0)  # r_i de falha imediata
    rod_damage_base: float = Field(0.002, ge=0.0)  # ΔD por ciclo em r = 1
    rod_damage_slope: float = Field(20.0, ge=0.0)  # (-)
    rod_weight_range: tuple[float, float] = (0.9, 1.1)  # w_i sorteado por sessão
    # --- sobre-rotação (RF-15, RF-16)
    valve_float_damage_per_100rpm: float = Field(0.004, ge=0.0)  # ΔD por ciclo a cada 100 rpm
    valve_contact_ratio: float = Field(1.08, gt=1.0)  # × valve_float_rpm
    bearing_overrev_rate: float = Field(0.4, ge=0.0)  # 1/s
    turbo_overspeed_rate: float = Field(1.0, ge=0.0)  # 1/s
    turbo_burst_ratio: float = Field(1.12, gt=1.0)  # × turbo_max_rpm
    # --- pressão de pico (RF-17)
    peak_pressure_damage: float = Field(0.01, ge=0.0)  # ΔD por ciclo por unidade de excesso
    # --- pré-ignição (RF-07, RF-08)
    preignition_p0: float = Field(1.0e-3, ge=0.0, le=0.1)  # probabilidade base por ciclo
    preignition_dt_scale_c: float = Field(15.0, gt=0.0)  # °C
    preignition_threshold_c: dict[str, float] = Field(
        default_factory=_default_preignition_thresholds
    )  # °C por combustível
    preignition_window_c: float = Field(60.0, gt=0.0)  # ativo se T_hs ≥ T_thr − janela
    preignition_p_max: float = Field(0.3, gt=0.0, le=1.0)  # teto de p_pi por ciclo
    preignition_iat_ref_c: float = Field(40.0)  # °C de f_iat
    preignition_iat_scale_c: float = Field(20.0, gt=0.0)  # °C de f_iat
    preignition_iat_clip: tuple[float, float] = (0.5, 4.0)  # limites de f_iat
    preignition_map_ref_kpa: float = Field(200.0, gt=0.0)  # kPa de f_load
    preignition_runaway_cycles: int = Field(10, ge=0, le=100)  # ciclos com ×3
    preignition_runaway_factor: float = Field(3.0, ge=1.0)
    hot_spot_theta_btdc: float = Field(35.0, ge=0.0, le=90.0)  # θ_pi do ponto quente
    lspi_theta_btdc: float = Field(40.0, ge=0.0, le=90.0)  # θ_pi da LSPI
    preignition_pressure_slope: float = Field(0.035, ge=0.0)  # por grau de θ_pi − avanço
    mega_knock_intensity_factor: float = Field(0.25, gt=0.0)  # I = fator · p_pi / 100
    preignition_piston_damage: float = Field(0.15, ge=0.0)  # ΔD = fator · p_pi / p_lim
    preignition_failure_ratio: float = Field(1.3, gt=1.0)  # falha se p_pi ≥ razão · p_lim
    lspi_enabled: bool = True
    lspi_rpm_range: tuple[float, float] = (1200.0, 3000.0)  # rev/min
    # LSPI (1.2.0): limiar acima do IMEP de série a baixa rotação (2530 kPa no hatch) e
    # probabilidades 10× menores (1e-5 a 2e-4 por ciclo, faixa medida em motores GDI)
    lspi_imep_min_kpa: float = Field(2700.0, gt=0.0)  # kPa
    lspi_imep_scale_kpa: float = Field(300.0, gt=0.0)  # kPa
    lspi_p_base: float = Field(1.0e-5, ge=0.0)
    lspi_p_max: float = Field(2.0e-4, gt=0.0, le=1.0)
    bearing_rod_share: float = Field(0.25, ge=0.0, le=1.0)  # fração do ΔD da biela
    burned_gas_temp_k: float = Field(2500.0, ge=1500.0, le=3200.0)  # K
    burned_gas_gamma: float = Field(1.28, ge=1.2, le=1.35)  # (-)
    # --- buffer forense e avisos
    trace_window_s: float = Field(30.0, ge=10.0, le=60.0)  # s
    warning_health_threshold: float = Field(0.50, gt=0.0, lt=1.0)  # (-)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.knock_window_end_deg_atdc <= self.knock_window_start_deg_atdc:
            raise ValueError("knock_window_end_deg_atdc deve ser maior que o início")
        low, high = self.rod_weight_range
        if not 0.5 <= low <= high <= 1.5:  # noqa: PLR2004
            raise ValueError("rod_weight_range deve ser (mín, máx) dentro de 0,5..1,5")
        if self.knock_sensor_gain is not None and not 1 <= len(self.knock_sensor_gain) <= 8:  # noqa: PLR2004
            raise ValueError("knock_sensor_gain deve ter 1..8 valores")
        missing = set(FUEL_IDS) - set(self.preignition_threshold_c)
        unknown = set(self.preignition_threshold_c) - set(FUEL_IDS)
        if missing or unknown:
            raise ValueError(
                f"preignition_threshold_c exige os 4 combustíveis "
                f"(faltam {sorted(missing)}, desconhecidos {sorted(unknown)})"
            )
        if len(set(self.features)) != len(self.features):
            raise ValueError("features com duplicados")
        return self

    def enabled(self, feature: DamageFeature) -> bool:
        """Indica se a capacidade ``feature`` está ligada."""
        return feature in self.features

    def preignition_threshold_for(self, fuel_id: str, ethanol_pct: float | None = None) -> float:
        """Limiar de ponto quente (°C) do combustível.

        ``flex``: interpolação linear entre E27 e E100 pelo peso do blend; sem
        ``ethanol_pct``, o menor dos dois limiares (conservador).
        """
        if fuel_id != FLEX_FUEL_ID:
            return self.preignition_threshold_c[fuel_id]
        low = self.preignition_threshold_c["e27"]
        high = self.preignition_threshold_c["e100"]
        if ethanol_pct is None:
            return min(low, high)
        t = blend_weight(min(max(ethanol_pct, ETHANOL_PCT_MIN), ETHANOL_PCT_MAX))
        return low + (high - low) * t

    def sensor_gains(self, n_cyl: int) -> list[float]:
        """Ganho ``g_i`` do sensor por cilindro (0,85 nas pontas, 1,0 nos centrais)."""
        if not 1 <= n_cyl <= MAX_CYLINDERS:
            raise ValueError(f"n_cyl fora de 1..{MAX_CYLINDERS}")
        if self.knock_sensor_gain is not None:
            if len(self.knock_sensor_gain) != n_cyl:
                raise ValueError("knock_sensor_gain não tem n_cyl valores")
            return list(self.knock_sensor_gain)
        return [
            END_CYLINDER_GAIN if i in (0, n_cyl - 1) and n_cyl > 2 else CENTER_CYLINDER_GAIN  # noqa: PLR2004
            for i in range(n_cyl)
        ]


DEFAULT_DAMAGE_CONFIG: Final = DamageConfig()
"""Configuração padrão versionada (``DAMAGE_CONFIG_VERSION``)."""
