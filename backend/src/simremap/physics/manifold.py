"""Coletores 0D por filling & emptying (Apêndice A.2; RF-04).

Primitivas: escoamento compressível por orifício (Ψ com regularização linear perto de
``p_dn/p_up → 1``), área efetiva da borboleta, taxa de pressão de um volume isotérmico e o
integrador de pressões.

Integrador: os orifícios largos (borboleta aberta, turbina, bypass) tornam o sistema de
pressões rígido a ``dt`` = 1 ms (autovalores de −10³ a −10⁴ s⁻¹), fora da região de
estabilidade do Heun explícito. As pressões avançam por Euler linearmente implícito
(Rosenbrock de 1.ª ordem, ``x' = x + h · (I − hJ)⁻¹ · f(x)``, Jacobiano por diferenças
finitas), que preserva exatamente o ponto de equilíbrio e é A-estável. O eixo do turbo
continua com Heun (ver ``turbo.py``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

__all__ = [
    "CD_THROTTLE",
    "GAMMA_AIR",
    "R_AIR",
    "idle_area_fraction",
    "linear_implicit_step",
    "orifice_flow",
    "psi",
    "throttle_area_m2",
    "volume_rate_kpa_s",
]

R_AIR = 287.05  # J/(kg·K)
GAMMA_AIR = 1.40
CD_THROTTLE = 0.85
IDLE_AREA_FRACTION = 0.004
PR_LINEAR = 0.98  # acima desta razão Ψ cai linearmente até 0 em pr = 1 (regularização)
FD_STEP_KPA = 0.01


def idle_area_fraction() -> float:
    return IDLE_AREA_FRACTION


def _psi_raw(pr: float, gamma: float) -> float:
    crit = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
    if pr <= crit:
        expo = (gamma + 1.0) / (2.0 * (gamma - 1.0))
        return float(math.sqrt(gamma) * (2.0 / (gamma + 1.0)) ** expo)
    val = pr ** (2.0 / gamma) - pr ** ((gamma + 1.0) / gamma)
    return math.sqrt(2.0 * gamma / (gamma - 1.0) * max(val, 0.0))


_PSI_LIN_CACHE: dict[float, float] = {}


def psi(pr: float, gamma: float = GAMMA_AIR) -> float:
    """Função de escoamento Ψ(p_dn/p_up) (A.2), bloqueada abaixo da razão crítica.

    Para ``pr > 0,98`` usa-se o segmento linear até Ψ = 0 em ``pr = 1`` (derivada finita).
    """
    if pr >= 1.0:
        return 0.0
    if pr > PR_LINEAR:
        lin = _PSI_LIN_CACHE.get(gamma)
        if lin is None:
            lin = _psi_raw(PR_LINEAR, gamma)
            _PSI_LIN_CACHE[gamma] = lin
        return lin * (1.0 - pr) / (1.0 - PR_LINEAR)
    return _psi_raw(max(pr, 0.0), gamma)


def orifice_flow(  # noqa: PLR0917
    cd_area_m2: float,
    p_up_kpa: float,
    t_up_k: float,
    p_dn_kpa: float,
    t_dn_k: float,
    gamma: float = GAMMA_AIR,
    r_gas: float = R_AIR,
) -> float:
    """Vazão mássica (kg/s) por orifício ``C_d·A`` com sinal (positiva de up para dn)."""
    if cd_area_m2 <= 0.0:
        return 0.0
    if p_up_kpa >= p_dn_kpa:
        if p_up_kpa <= 0.0:
            return 0.0
        return (
            cd_area_m2
            * 1000.0
            * p_up_kpa
            / math.sqrt(r_gas * t_up_k)
            * psi(p_dn_kpa / p_up_kpa, gamma)
        )
    return -(
        cd_area_m2 * 1000.0 * p_dn_kpa / math.sqrt(r_gas * t_dn_k) * psi(p_up_kpa / p_dn_kpa, gamma)
    )


def throttle_area_m2(tps_pct: float, diameter_m: float) -> float:
    """``A(tps) = A_idle + (A_max − A_idle) · (1 − cos(π/2 · tps/100))`` (m²)."""
    a_max = math.pi / 4.0 * diameter_m * diameter_m
    a_idle = IDLE_AREA_FRACTION * a_max
    tps = min(max(tps_pct, 0.0), 100.0)
    return a_idle + (a_max - a_idle) * (1.0 - math.cos(math.pi / 2.0 * tps / 100.0))


def volume_rate_kpa_s(r_gas: float, t_k: float, volume_m3: float, net_kg_s: float) -> float:
    """``dp/dt = (R · T / V) · Σṁ / 1000`` (kPa/s), volume isotérmico."""
    return r_gas * t_k / volume_m3 * net_kg_s / 1000.0


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Eliminação de Gauss com pivotagem parcial (n ≤ 4), sem NumPy no hot path."""
    n = len(b)
    m = [[*row[:], b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if m[piv][col] == 0.0:
            raise ZeroDivisionError("matriz singular no integrador de pressões")
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            factor = m[r][col] * inv
            if factor != 0.0:
                row_r = m[r]
                row_c = m[col]
                for c in range(col, n + 1):
                    row_r[c] -= factor * row_c[c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        acc = m[r][n]
        for c in range(r + 1, n):
            acc -= m[r][c] * x[c]
        x[r] = acc / m[r][r]
    return x


def linear_implicit_step(
    rates: Callable[[Sequence[float]], list[float]],
    x: list[float],
    h: float,
    f0: list[float] | None = None,
) -> list[float]:
    """Um passo de Euler linearmente implícito ``x + h·(I − hJ)⁻¹·f(x)``.

    ``J`` vem de diferenças finitas progressivas de ``rates`` (passo 0,01 kPa).
    """
    n = len(x)
    if n == 0:
        return []
    f = rates(x) if f0 is None else f0
    jac_cols: list[list[float]] = []
    for j in range(n):
        xp = list(x)
        xp[j] += FD_STEP_KPA
        fp = rates(xp)
        jac_cols.append([(fp[i] - f[i]) / FD_STEP_KPA for i in range(n)])
    a = [[(1.0 if i == j else 0.0) - h * jac_cols[j][i] for j in range(n)] for i in range(n)]
    dx = _solve(a, [h * fi for fi in f])
    return [x[i] + dx[i] for i in range(n)]
