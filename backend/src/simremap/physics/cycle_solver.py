"""Ciclo fechado de zona única com γ(T) e Woschni a 1° de cambota (Apêndice A.5; RF-03, RF-10).

Cada evento de combustão resolve IVC → EVO com Heun a 1°. As entradas do solver são
quantizadas (rpm 10 rpm, massa de ar 0,2 %, λ 0,002, avanço 0,25°, T_ivc 1 K, x_r 0,002,
T_parede 1 K) e o solver usa SEMPRE os valores quantizados; por isso o resultado é idêntico
com ou sem acerto na cache LRU (D-06, EC-12) e o digest não depende do tamanho da cache.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from simremap.catalog.contracts import FUEL_IDS, EngineSpec, FuelSpec
from simremap.physics.combustion import (
    COMBUSTION_EFFICIENCY,
    FlameCoefficients,
    burn_duration_deg,
    ignition_delay_deg,
    wiebe_fraction,
)
from simremap.physics.geometry import DEG_OFFSET, CylinderGeometry, mean_piston_speed
from simremap.physics.kernels import build_cycle_kernel, use_native

__all__ = [
    "R_MIX",
    "CycleInputs",
    "CycleKey",
    "CycleResult",
    "CycleSolver",
    "gamma_of_t",
    "internal_energy_per_kg",
    "quantize_inputs",
]

R_MIX = 287.0  # J/(kg·K)
GAMMA_A = 1.392
GAMMA_B = 8.13e-5
GAMMA_MIN = 1.20
GAMMA_MAX = 1.40
T_GAMMA_SAT = (GAMMA_A - GAMMA_MIN) / GAMMA_B  # K, acima disto γ = 1,20
WOSCHNI_C1 = 2.28
WOSCHNI_C2 = 3.24e-3  # m/(s·K), combustão/expansão
POLYTROPIC_MOTORED = 1.30
P_CRANKCASE_PA = 100_000.0

# Passos de quantização (seção 15 da spec).
Q_RPM = 10.0
Q_MASS_LOG = math.log(1.002)
Q_LAMBDA = 0.002
Q_ADVANCE = 0.25
Q_T_IVC = 1.0
Q_XR = 0.002
Q_T_WALL = 1.0

CycleKey = tuple[int, int, int, int, int, int, int, int, int, int, int]


def gamma_of_t(t_k: float) -> float:
    """``γ(T) = 1,392 − 8,13·10⁻⁵ · T`` saturado em [1,20; 1,40]."""
    g = GAMMA_A - GAMMA_B * t_k
    if g < GAMMA_MIN:
        return GAMMA_MIN
    if g > GAMMA_MAX:
        return GAMMA_MAX
    return g


def internal_energy_per_kg(t_k: float) -> float:
    """``u(T) = ∫ R/(γ(T) − 1) dT`` (J/kg, referência arbitrária) coerente com ``γ(T)``."""
    t_low = (GAMMA_A - GAMMA_MAX) / GAMMA_B  # < 0: γ nunca satura em 1,40 para T > 0
    if t_k <= T_GAMMA_SAT:
        t = max(t_k, t_low + 1e-9)
        return -(R_MIX / GAMMA_B) * math.log(GAMMA_A - 1.0 - GAMMA_B * t)
    u_sat = -(R_MIX / GAMMA_B) * math.log(GAMMA_A - 1.0 - GAMMA_B * T_GAMMA_SAT)
    return u_sat + R_MIX / (GAMMA_MIN - 1.0) * (t_k - T_GAMMA_SAT)


@dataclass(frozen=True, slots=True)
class CycleInputs:
    """Entradas (já quantizadas) de um ciclo fechado."""

    rpm: float  # rev/min
    m_air_kg: float  # kg de ar aprisionado
    lam: float  # (-); 0 = sem combustível no cilindro
    x_r: float  # fração mássica de gás residual
    t_ivc_k: float  # K
    advance_deg: float  # ° BTDC
    ivc_deg: int  # ° local (negativo)
    evo_deg: int  # ° local (positivo)
    t_wall_k: float  # K
    fire: bool  # False = sem libertação de calor (misfire, corte)
    fuel_index: int  # posição em FUEL_IDS (ou índice próprio de um blend flex)


@dataclass(frozen=True, slots=True)
class CycleResult:
    """Resultado de um ciclo IVC → EVO (pressão em Pa a cada 1°)."""

    inputs: CycleInputs
    pressure_pa: tuple[float, ...]  # (θ_EVO − θ_IVC) + 1 pontos
    temperature_k: tuple[float, ...]
    m_total_kg: float
    m_fuel_kg: float
    q_available_j: float  # min(m_f, m_a/AFR) · PCI
    q_comb_j: float  # calor libertado até ao EVO
    q_wall_j: float  # calor para a parede (positivo = perda)
    work_j: float  # ∮ p dV, IVC → EVO
    du_j: float  # variação de energia interna
    energy_error: float  # |Q_c − W − Q_w − ΔU| / referência
    p_max_pa: float
    theta_pmax_deg: float  # ° ATDC (interpolação parabólica)
    t_evo_k: float
    p_evo_pa: float
    xb_evo: float
    burn_duration_deg: float
    theta0_deg: float  # início da combustão
    spark_deg: float  # = −avanço
    unburned_chem_j: float  # energia química que segue para o escape
    event_theta_start: int  # ° do primeiro ponto (≥ faísca)
    event_pressure_kpa: tuple[float, ...]  # faísca → fim de combustão
    event_t_unburned_k: tuple[float, ...]
    event_burned_fraction: tuple[float, ...]
    t_unburned_max_k: float


def quantize_inputs(
    rpm: float,
    m_air_kg: float,
    lam: float,
    x_r: float,
    t_ivc_k: float,
    advance_deg: float,
    ivc_deg: int,
    evo_deg: int,
    t_wall_k: float,
    fire: bool,
    fuel_index: int,
) -> tuple[CycleKey, CycleInputs]:
    """Quantiza as entradas e devolve a chave da cache e as entradas reconstruídas."""
    q_rpm = max(1, round(rpm / Q_RPM))
    q_mass = round(math.log(max(m_air_kg, 1e-9) * 1e6) / Q_MASS_LOG)  # em mg, escala log
    q_lam = round(lam / Q_LAMBDA) if lam > 0.0 else 0
    q_xr = round(min(max(x_r, 0.0), 0.5) / Q_XR)
    q_tivc = round(t_ivc_k / Q_T_IVC)
    q_adv = round(advance_deg / Q_ADVANCE)
    q_twall = round(t_wall_k / Q_T_WALL)
    key: CycleKey = (
        q_rpm,
        q_mass,
        q_lam,
        q_xr,
        q_tivc,
        q_adv,
        ivc_deg,
        evo_deg,
        q_twall,
        1 if fire else 0,
        fuel_index,
    )
    inputs = CycleInputs(
        rpm=q_rpm * Q_RPM,
        m_air_kg=math.exp(q_mass * Q_MASS_LOG) * 1e-6,
        lam=q_lam * Q_LAMBDA,
        x_r=q_xr * Q_XR,
        t_ivc_k=q_tivc * Q_T_IVC,
        advance_deg=q_adv * Q_ADVANCE,
        ivc_deg=ivc_deg,
        evo_deg=evo_deg,
        t_wall_k=q_twall * Q_T_WALL,
        fire=fire and q_lam > 0,
        fuel_index=fuel_index,
    )
    return key, inputs


@dataclass(frozen=True, slots=True)
class _FuelThermo:
    afr: float
    lhv_j_kg: float
    flame: FlameCoefficients


class CycleSolver:
    """Solver de zona única com cache LRU de entradas quantizadas."""

    def __init__(
        self,
        geometry: CylinderGeometry,
        engine: EngineSpec,
        wiebe_a: float,
        wiebe_m: float,
        cache_size: int,
        *,
        native: bool | None = None,
    ) -> None:
        self.geo = geometry
        self.wiebe_a = wiebe_a
        self.wiebe_m = wiebe_m
        self.duration_ref_deg = engine.wiebe_duration_ref_deg
        self.rpm_ref = engine.wiebe_rpm_ref
        self.cache_size = cache_size
        self._cache: OrderedDict[CycleKey, CycleResult] = OrderedDict()
        self._fuels: dict[int, _FuelThermo] = {}
        self._blend_index: dict[_FuelThermo, int] = {}
        self.hits = 0
        self.misses = 0
        self._woschni_k = 3.26 * geometry.bore_m**-0.2
        # Kernel nativo (feature 003): ``None`` segue ``SIMREMAP_NATIVE``; ``False`` força o Python.
        self._kernel: Any = None
        if use_native(native):
            self._kernel = build_cycle_kernel(
                geometry,
                woschni_k=self._woschni_k,
                wiebe_a=wiebe_a,
                wiebe_m=wiebe_m,
                duration_ref_deg=self.duration_ref_deg,
                rpm_ref=self.rpm_ref,
            )

    def disable_native(self) -> None:
        """Volta à referência Python (o resultado é o mesmo; só muda o custo)."""
        self._kernel = None

    @property
    def native(self) -> bool:
        """``True`` quando ``solve_uncached`` corre no ``CycleKernel`` em Rust."""
        return self._kernel is not None

    # ------------------------------------------------------------------ combustíveis
    def register_fuel(self, fuel: FuelSpec) -> int:
        """Regista o combustível e devolve o seu índice de cache.

        Combustíveis do catálogo usam a posição em ``FUEL_IDS``; cada blend ``flex``
        distinto (termoquímica diferente) recebe um índice próprio a partir de
        ``len(FUEL_IDS)``, para que blends diferentes nunca partilhem resultados.
        """
        thermo = _FuelThermo(
            afr=fuel.afr_stoich,
            lhv_j_kg=fuel.lhv_mj_kg * 1e6,
            flame=FlameCoefficients.from_fuel(fuel),
        )
        if fuel.fuel_id in FUEL_IDS:
            index = FUEL_IDS.index(fuel.fuel_id)
        else:
            index = self._blend_index.setdefault(thermo, len(FUEL_IDS) + len(self._blend_index))
        self._fuels[index] = thermo
        # Um FuelSpec diferente com o mesmo id invalida resultados antigos desse índice.
        stale = [k for k in self._cache if k[10] == index]
        for k in stale:
            del self._cache[k]
        return index

    # ------------------------------------------------------------------ cache
    def solve(self, key: CycleKey, inputs: CycleInputs) -> CycleResult:
        """Resolve o ciclo, consultando a cache (resultado idêntico com ou sem acerto)."""
        if self.cache_size <= 0:
            self.misses += 1
            return self.solve_uncached(inputs)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self.hits += 1
            return cached
        self.misses += 1
        result = self.solve_uncached(inputs)
        self._cache[key] = result
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return result

    def cache_len(self) -> int:
        return len(self._cache)

    def clear_cache(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------ solver
    def solve_uncached(self, inp: CycleInputs) -> CycleResult:
        """Resolve o ciclo sem cache (Rust se disponível; senão a referência Python)."""
        kernel = self._kernel
        if kernel is None:
            return self.solve_uncached_py(inp)
        fuel = self._fuels[inp.fuel_index]
        flame = fuel.flame
        out = kernel.solve(
            inp.rpm,
            inp.m_air_kg,
            inp.lam,
            inp.x_r,
            inp.t_ivc_k,
            inp.advance_deg,
            inp.ivc_deg,
            inp.evo_deg,
            inp.t_wall_k,
            inp.fire,
            fuel.afr,
            fuel.lhv_j_kg,
            flame.b_m,
            flame.b_phi,
            flame.phi_m,
        )
        return CycleResult(inp, *out)

    def solve_uncached_py(self, inp: CycleInputs) -> CycleResult:  # noqa: PLR0915
        """Implementação de referência em Python puro (paridade do kernel nativo)."""
        geo = self.geo
        fuel = self._fuels[inp.fuel_index]
        vol = geo.volume_m3
        dvol = geo.dvol_m3_per_deg
        area = geo.wall_area_m2
        i0 = inp.ivc_deg + DEG_OFFSET
        i1 = inp.evo_deg + DEG_OFFSET
        rpm = inp.rpm
        m_air = inp.m_air_kg
        m_fuel = m_air / (inp.lam * fuel.afr) if inp.lam > 0.0 else 0.0
        m_tot = (m_air + m_fuel) / (1.0 - inp.x_r)
        t_ivc = inp.t_ivc_k
        v_ivc = vol[i0]
        p_ivc = m_tot * R_MIX * t_ivc / v_ivc
        mr = m_tot * R_MIX
        t_wall = inp.t_wall_k
        q_avail = min(m_fuel, m_air / fuel.afr) * fuel.lhv_j_kg if m_fuel > 0.0 else 0.0
        q_tot = COMBUSTION_EFFICIENCY * q_avail if inp.fire else 0.0
        sp = mean_piston_speed(geo.stroke_m, rpm)
        c1sp = WOSCHNI_C1 * sp
        dt_deg = 1.0 / (6.0 * rpm)
        hk = self._woschni_k * dt_deg
        c2k = WOSCHNI_C2 * geo.vd_cyl_m3 * t_ivc / (p_ivc / 1000.0 * v_ivc) / 1000.0
        a_w = self.wiebe_a
        m_w = self.wiebe_m
        mp1 = m_w + 1.0
        spark = -inp.advance_deg
        theta0 = spark + ignition_delay_deg(rpm)
        duration = -1.0  # calculada ao atingir a faísca (estado de fim de compressão)
        rate_k = 0.0

        def dq_comb(theta: float) -> float:
            if duration <= 0.0 or theta <= theta0 or theta > theta0 + duration:
                return 0.0
            y = (theta - theta0) / duration
            return float(rate_k * y**m_w * math.exp(-a_w * y**mp1))

        def deriv(i: int, p: float, dqc: float, comb: bool) -> tuple[float, float]:
            v = vol[i]
            t = p * v / mr
            g = GAMMA_A - GAMMA_B * t
            g = GAMMA_MIN if g < GAMMA_MIN else min(g, GAMMA_MAX)
            w = c1sp
            if comb:
                p_mot = p_ivc * (v_ivc / v) ** POLYTROPIC_MOTORED
                w += c2k * (p - p_mot)
                w = max(w, c1sp)
            h_dt = hk * (p / 1000.0) ** 0.8 * t**-0.55 * w**0.8
            dqw = h_dt * area[i] * (t - t_wall)
            return ((g - 1.0) * (dqc - dqw) - g * p * dvol[i]) / v, dqw

        n = i1 - i0 + 1
        pres = [0.0] * n
        temp = [0.0] * n
        pres[0] = p_ivc
        temp[0] = t_ivc
        p = p_ivc
        work = 0.0
        q_wall = 0.0
        q_comb = 0.0
        w_abs = 0.0
        comb = False
        dqc0 = 0.0
        for k in range(n - 1):
            i = i0 + k
            th1 = float(i + 1 - DEG_OFFSET)
            if duration < 0.0 and th1 >= spark:
                t_now = p * vol[i] / mr
                lam_eff = inp.lam if inp.lam > 0.0 else 1.0
                duration = burn_duration_deg(
                    rpm,
                    lam_eff,
                    fuel.flame,
                    inp.x_r,
                    t_now,
                    p / 1000.0,
                    self.duration_ref_deg,
                    self.rpm_ref,
                )
                rate_k = q_tot * a_w * mp1 / duration
            f1, dqw1 = deriv(i, p, dqc0, comb)
            p_pred = p + f1
            if p_pred <= 0.0:
                p_pred = p * 0.5
            comb = comb or (duration > 0.0 and th1 > theta0)
            dqc1 = dq_comb(th1)
            f2, dqw2 = deriv(i + 1, p_pred, dqc1, comb)
            p_new = p + 0.5 * (f1 + f2)
            dv = vol[i + 1] - vol[i]
            dw = 0.5 * (p + p_new) * dv
            work += dw
            w_abs += abs(dw)
            q_wall += 0.5 * (dqw1 + dqw2)
            q_comb += 0.5 * (dqc0 + dqc1)
            p = p_new
            pres[k + 1] = p
            temp[k + 1] = p * vol[i + 1] / mr
            dqc0 = dqc1

        if duration < 0.0:  # faísca depois do EVO: sem combustão no ciclo fechado
            duration = burn_duration_deg(
                rpm,
                1.0,
                fuel.flame,
                inp.x_r,
                t_ivc,
                p_ivc / 1000.0,
                self.duration_ref_deg,
                self.rpm_ref,
            )
        t_evo = temp[-1]
        du = m_tot * (internal_energy_per_kg(t_evo) - internal_energy_per_kg(t_ivc))
        ref = q_comb if q_comb > 0.0 else max(w_abs, 1e-9)
        energy_error = abs(q_comb - work - q_wall - du) / ref

        # Pico de pressão com refinamento parabólico.
        k_max = max(range(n), key=pres.__getitem__)
        theta_pk = float(k_max + inp.ivc_deg)
        if 0 < k_max < n - 1:
            pa, pb, pc = pres[k_max - 1], pres[k_max], pres[k_max + 1]
            denom = pa - 2.0 * pb + pc
            if denom < 0.0:
                theta_pk += 0.5 * (pa - pc) / denom
        xb_evo = wiebe_fraction(float(inp.evo_deg), theta0, duration, a_w, m_w) if inp.fire else 0.0
        unburned = m_fuel * fuel.lhv_j_kg - q_comb

        # Janela do evento: faísca → fim da combustão (inclusive), recortada a [IVC, EVO].
        start = max(math.ceil(spark), inp.ivc_deg)
        end = min(math.ceil(theta0 + duration), inp.evo_deg)
        end = max(end, start)
        ev_p: list[float] = []
        ev_tu: list[float] = []
        ev_xb: list[float] = []
        g_u = gamma_of_t(t_ivc)
        tu = t_ivc
        tu_max = t_ivc
        for k in range(n):
            theta = k + inp.ivc_deg
            pk = pres[k]
            tu = t_ivc * (pk / p_ivc) ** ((g_u - 1.0) / g_u)
            g_u = gamma_of_t(tu)
            if theta >= start:
                if theta > end:
                    break
                ev_p.append(pk / 1000.0)
                ev_tu.append(tu)
                ev_xb.append(
                    wiebe_fraction(float(theta), theta0, duration, a_w, m_w) if inp.fire else 0.0
                )
                tu_max = max(tu_max, tu)
        return CycleResult(
            inputs=inp,
            pressure_pa=tuple(pres),
            temperature_k=tuple(temp),
            m_total_kg=m_tot,
            m_fuel_kg=m_fuel,
            q_available_j=q_avail,
            q_comb_j=q_comb,
            q_wall_j=q_wall,
            work_j=work,
            du_j=du,
            energy_error=energy_error,
            p_max_pa=pres[k_max],
            theta_pmax_deg=theta_pk,
            t_evo_k=t_evo,
            p_evo_pa=pres[-1],
            xb_evo=xb_evo,
            burn_duration_deg=duration,
            theta0_deg=theta0,
            spark_deg=spark,
            unburned_chem_j=max(unburned, 0.0),
            event_theta_start=start,
            event_pressure_kpa=tuple(ev_p),
            event_t_unburned_k=tuple(ev_tu),
            event_burned_fraction=tuple(ev_xb),
            t_unburned_max_k=tu_max,
        )
