"""Sinais de aviso antecipados do laudo (RF-24; Apêndice C.2).

Cada regra devolve a primeira ocorrência no buffer, até o instante da falha, com
``lead_time_s = t_falha − t_sinal``.
"""

from __future__ import annotations

from typing import Final

import numpy as np

from simremap.damage.contracts import EarlyWarning
from simremap.damage.forensic.view import MAX_RETARD_DEG, Crossing, TraceView

__all__ = [
    "HEALTH_LOW",
    "detect_early_warnings",
    "first_retard_rising",
    "first_retard_saturated",
]

RETARD_RISE_DEG: Final = 2.0
RETARD_RISE_WINDOW_S: Final = 1.0
RETARD_SATURATED_S: Final = 0.2
EGT_MARGIN_C: Final = 30.0
LEAN_LAMBDA: Final = 0.90
LEAN_MAP_KPA: Final = 150.0
LEAN_DURATION_S: Final = 0.3
ROD_TORQUE_SHARE: Final = 0.95
HEALTH_LOW: Final = 0.75
TURBO_SHARE: Final = 0.95
IAT_HIGH_C: Final = 60.0
HOT_SPOT_MARGIN_C: Final = 30.0
_EPS: Final = 1e-9


def first_retard_rising(view: TraceView) -> Crossing | None:
    """Retardo de knock de um cilindro sobe ≥ 2° numa janela de 1 s."""
    retard = view.tick("knock_retard_deg")
    t = view.t
    if retard.size == 0 or np.isnan(retard).all():
        return None
    best: Crossing | None = None
    for cyl in range(retard.shape[1]):
        series = retard[:, cyl]
        lo = 0
        for k in range(t.size):
            while float(t[k]) - float(t[lo]) > RETARD_RISE_WINDOW_S + _EPS:
                lo += 1
            window = series[lo : k + 1]
            if np.isnan(series[k]) or np.isnan(window).all():
                continue
            if float(series[k]) - float(np.nanmin(window)) >= RETARD_RISE_DEG - _EPS:
                if best is None or float(t[k]) < best.t_sim_s:
                    best = Crossing(float(t[k]), float(series[k]), cyl + 1)
                break
    return best


def first_retard_saturated(view: TraceView) -> Crossing | None:
    """Retardo ≥ 8° durante ≥ 0,2 s em algum cilindro."""
    retard = view.tick("knock_retard_deg")
    if retard.size == 0:
        return None
    best: Crossing | None = None
    for cyl in range(retard.shape[1]):
        series = retard[:, cyl]
        hit = view.first_sustained(series >= MAX_RETARD_DEG - _EPS, series, RETARD_SATURATED_S)
        if hit is not None and (best is None or hit.t_sim_s < best.t_sim_s):
            best = Crossing(hit.t_sim_s, hit.value, cyl + 1)
    return best


def _warning(
    signal: str, hit: Crossing | None, threshold: float, unit: str, t_f: float
) -> EarlyWarning | None:
    if hit is None or hit.t_sim_s > t_f + _EPS:
        return None
    return EarlyWarning.model_validate(
        {
            "signal": signal,
            "t_sim_s": max(0.0, hit.t_sim_s),
            "lead_time_s": max(0.0, round(t_f - hit.t_sim_s, 9)),
            "cylinder": hit.cylinder,
            "value": round(hit.value, 6),
            "threshold": threshold,
            "unit": unit,
        }
    )


def detect_early_warnings(view: TraceView) -> list[EarlyWarning]:
    """Aplica as 10 regras do Apêndice C.2 (ordem por ``t_sim_s``)."""
    trace = view.trace
    limits = trace.meta.limits
    t_f = view.t_f
    found: list[EarlyWarning | None] = [
        _warning("knock_retard_rising", first_retard_rising(view), RETARD_RISE_DEG, "deg", t_f)
    ]
    classes = view.cycle("knock_class")
    k = view.first_cycle(classes >= 2.0)  # noqa: PLR2004 - código de "moderate"
    if k is not None:
        hit = Crossing(
            float(view.cycle("t_sim_s")[k]),
            float(view.cycle("intensity")[k]),
            int(view.cycle("cylinder")[k]),
        )
        found.append(_warning("first_moderate_knock", hit, 1.0, "bar", t_f))
    found.append(
        _warning("knock_retard_saturated", first_retard_saturated(view), MAX_RETARD_DEG, "deg", t_f)
    )
    egt = view.tick("egt_collector_c")
    egt_threshold = limits.egt_limit_c - EGT_MARGIN_C
    found.append(
        _warning(
            "egt_near_limit", view.first_true(egt >= egt_threshold, egt), egt_threshold, "C", t_f
        )
    )
    lam = view.lambda_series()
    loaded = view.tick("map_kpa") >= LEAN_MAP_KPA
    found.append(
        _warning(
            "lean_under_load",
            view.first_sustained((lam >= LEAN_LAMBDA - _EPS) & loaded, lam, LEAN_DURATION_S),
            LEAN_LAMBDA,
            "lambda",
            t_f,
        )
    )
    torque = view.tick("torque_nm")
    torque_threshold = ROD_TORQUE_SHARE * limits.rod_torque_limit_nm
    found.append(
        _warning(
            "rod_torque_near_limit",
            view.first_true(torque >= torque_threshold, torque),
            torque_threshold,
            "N.m",
            t_f,
        )
    )
    health = view.tick("health")
    if health.size:
        rows = np.flatnonzero((health < HEALTH_LOW).any(axis=1))
        if rows.size:
            row = int(rows[0])
            col = int(np.flatnonzero(health[row] < HEALTH_LOW)[0])
            component = trace.meta.component_ids[col]
            cyl = (
                int(component.split(":")[1])
                if component.split(":")[0]
                in (
                    "piston",
                    "rod",
                    "valves",
                )
                else None
            )
            hit = Crossing(float(view.t[row]), float(health[row, col]), cyl)
            found.append(_warning("component_health_low", hit, HEALTH_LOW, "health", t_f))
    if limits.turbo_max_rpm is not None:
        turbo = view.tick("turbo_rpm")
        turbo_threshold = TURBO_SHARE * limits.turbo_max_rpm
        found.append(
            _warning(
                "turbo_speed_near_limit",
                view.first_true(turbo >= turbo_threshold, turbo),
                turbo_threshold,
                "rpm",
                t_f,
            )
        )
    iat = view.tick("iat_c")
    found.append(
        _warning(
            "iat_high", view.first_true((iat >= IAT_HIGH_C) & loaded, iat), IAT_HIGH_C, "C", t_f
        )
    )
    hot_threshold = trace.meta.hot_spot_threshold_c - HOT_SPOT_MARGIN_C
    found.append(
        _warning(
            "hot_spot_near_threshold",
            view.first_cylinder_crossing("hot_spot_temp_c", hot_threshold),
            hot_threshold,
            "C",
            t_f,
        )
    )
    warnings = [w for w in found if w is not None]
    return sorted(warnings, key=lambda w: (w.t_sim_s, w.signal))
