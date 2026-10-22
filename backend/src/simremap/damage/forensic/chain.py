"""Cadeia causal do laudo (RF-23; Apêndice C.1).

O modelo de cadeia do mecanismo define os elos candidatos; entram só os que têm
evidência no buffer (variável acima do limiar). A cadeia sai ordenada por ``t_sim_s``
crescente, com 3 a 12 elos e o último elo igual à falha (ou ao fim da quase-falha).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import numpy as np

from simremap.damage.contracts import (
    MAX_CAUSAL_LINKS,
    CalibrationDiff,
    CausalLink,
    FailureEvent,
)
from simremap.damage.forensic.view import MAX_RETARD_DEG, TraceView
from simremap.damage.forensic.warnings import HEALTH_LOW, first_retard_saturated

__all__ = ["CHAIN_FAMILIES", "build_causal_chain", "chain_family"]

LinkKind = Literal[
    "calibration", "operating_point", "combustion", "ecu_response", "damage", "warning", "failure"
]
Family = Literal["knock", "thermal", "rod", "preignition", "overrev"]

CHAIN_FAMILIES: Final[dict[str, Family]] = {
    "knock_erosion": "knock",
    "ring_land_crack": "knock",
    "head_gasket_breach": "knock",
    "piston_thermal_melt": "thermal",
    "exhaust_valve_burn": "thermal",
    "turbine_creep": "thermal",
    "rod_overload": "rod",
    "rod_instant_bend": "rod",
    "bearing_spin": "rod",
    "hot_spot_preignition": "preignition",
    "lspi": "preignition",
    "valve_piston_contact": "overrev",
    "turbo_overspeed_burst": "overrev",
}
BOOST_EVIDENCE_KPA: Final = 10.0
SEVERE_CODE: Final = 3.0  # código de "severe" (e limiar em bar)
_EPS: Final = 1e-9


@dataclass(frozen=True, slots=True)
class _Candidate:
    rank: int  # ordem do modelo de cadeia (desempate)
    t: float
    kind: LinkKind
    variable: str
    value: float
    threshold: float | None
    unit: str
    description: str
    cylinder: int | None = None


def chain_family(mechanism: str | None) -> Family:
    """Família do modelo de cadeia; sem mecanismo (quase-falha por knock) ⇒ ``knock``."""
    return CHAIN_FAMILIES.get(mechanism or "", "knock")


def _calibration(
    view: TraceView, calibration_diff: CalibrationDiff | None, family: Family
) -> list[_Candidate]:
    t0 = view.t_start
    out: list[_Candidate] = []
    deltas = {d.table_id: d for d in (calibration_diff.deltas if calibration_diff else [])}
    boost = deltas.get("boost_target")
    if boost is not None and boost.max_delta > 0.0:
        out.append(
            _Candidate(
                0,
                t0,
                "calibration",
                "boost_target",
                boost.max_delta,
                0.0,
                "kPa",
                f"Boost alvo {boost.max_delta:+.0f} kPa acima da puxada base",
            )
        )
    ignition = deltas.get("ignition_base")
    if ignition is not None and ignition.max_delta > 0.0:
        out.append(
            _Candidate(
                0,
                t0,
                "calibration",
                "ignition_base",
                ignition.max_delta,
                0.0,
                "deg",
                f"Avanço base {ignition.max_delta:+.1f}° acima da puxada base",
            )
        )
    lam = deltas.get("lambda_target")
    if family == "thermal" and lam is not None and lam.max_delta > 0.0:
        out.append(
            _Candidate(
                0,
                t0,
                "calibration",
                "lambda_target",
                lam.max_delta,
                0.0,
                "lambda",
                f"Lambda alvo {lam.max_delta:+.2f} mais pobre que a puxada base",
            )
        )
    if out:
        return out
    stock = view.trace.meta.stock_boost_kpa
    target = view.tick("boost_target_kpa")
    if stock is not None and target.size and not np.isnan(target).all():
        peak = float(np.nanmax(target))
        if peak > stock + BOOST_EVIDENCE_KPA:
            out.append(
                _Candidate(
                    0,
                    t0,
                    "calibration",
                    "boost_target_kpa",
                    peak,
                    stock,
                    "kPa",
                    f"Boost alvo de {peak:.0f} kPa acima do valor de série ({stock:.0f} kPa)",
                )
            )
    return out


def _peak_operating_point(
    view: TraceView, name: str, unit: str, label: str, threshold: float | None
) -> _Candidate | None:
    data = view.tick(name)
    if data.size == 0 or np.isnan(data).all():
        return None
    k = int(np.nanargmax(data))
    value = float(data[k])
    if threshold is not None and value < threshold:
        return None
    return _Candidate(
        1,
        float(view.t[k]),
        "operating_point",
        name,
        value,
        threshold,
        unit,
        f"{label} máximo de {value:.0f} {unit}",
    )


def _first_class(view: TraceView, code: float, rank: int, label: str) -> _Candidate | None:
    k = view.first_cycle(view.cycle("knock_class") >= code)
    if k is None:
        return None
    cyl = int(view.cycle("cylinder")[k])
    intensity = float(view.cycle("intensity")[k])
    theta = float(view.cycle("theta_onset_deg_atdc")[k])
    theta_txt = "" if np.isnan(theta) else f", θ_k {theta:.0f}° ATDC"
    return _Candidate(
        rank,
        float(view.cycle("t_sim_s")[k]),
        "combustion",
        "knock_intensity",
        intensity,
        1.0 if code < SEVERE_CODE else SEVERE_CODE,
        "bar",
        f"Primeiro knock {label} no cilindro {cyl} (I {intensity:.1f} bar{theta_txt})",
        cyl,
    )


def _health_drops(view: TraceView, component_id: str | None, rank: int) -> list[_Candidate]:
    if component_id is None or component_id not in view.trace.meta.component_ids:
        return []
    series = view.trace.health_of(component_id)[: view.t.size]
    out: list[_Candidate] = []
    cyl = (
        int(component_id.split(":")[1])
        if component_id.split(":")[0] in ("piston", "rod", "valves")
        else None
    )
    for level in (HEALTH_LOW, 0.5):
        idx = np.flatnonzero(series < level)
        if idx.size:
            k = int(idx[0])
            out.append(
                _Candidate(
                    rank,
                    float(view.t[k]),
                    "damage",
                    f"health:{component_id}",
                    float(series[k]),
                    level,
                    "health",
                    f"Saúde de {component_id} abaixo de {level:.2f}",
                    cyl,
                )
            )
    return out


def _knock_family(view: TraceView) -> list[_Candidate]:
    out: list[_Candidate] = []
    hit = _first_class(view, 2.0, 2, "moderado")
    if hit:
        out.append(hit)
    saturated = first_retard_saturated(view)
    if saturated is not None:
        out.append(
            _Candidate(
                3,
                saturated.t_sim_s,
                "ecu_response",
                "knock_retard_deg",
                saturated.value,
                MAX_RETARD_DEG,
                "deg",
                f"Retardo de knock saturado em {saturated.value:.0f}° no cilindro "
                f"{saturated.cylinder}",
                saturated.cylinder,
            )
        )
    hit = _first_class(view, 3.0, 4, "severo")
    if hit:
        out.append(hit)
    return out


def _thermal_family(view: TraceView, mechanism: str | None) -> list[_Candidate]:
    limits = view.trace.meta.limits
    cfg = view.trace.meta.config
    if mechanism == "piston_thermal_melt":
        data = view.tick("piston_temp_eff_c")
        limit = limits.max_piston_temp_c
        label, name = "Temperatura efetiva do pistão", "piston_temp_eff_c"
    elif mechanism == "exhaust_valve_burn":
        data = view.tick("egt_c")
        limit = limits.egt_limit_c + cfg.valve_egt_margin_c
        label, name = "EGT do cilindro", "egt_c"
    else:
        data = view.tick("egt_collector_c")
        limit = limits.egt_limit_c
        label, name = "EGT pré-turbina", "egt_collector_c"
    if data.size == 0:
        return []
    flat = data if data.ndim == 1 else np.nanmax(np.where(np.isnan(data), -np.inf, data), axis=1)
    idx = np.flatnonzero(flat > limit)
    if idx.size == 0:
        return []
    k = int(idx[0])
    duration = float(view.t[idx[-1]]) - float(view.t[k])
    return [
        _Candidate(
            1,
            float(view.t[k]),
            "operating_point",
            name,
            float(np.max(flat[idx])),
            limit,
            "C",
            f"{label} acima de {limit:.0f} °C durante {duration:.1f} s",
        )
    ]


def _rod_family(view: TraceView) -> list[_Candidate]:
    limit = view.trace.meta.limits.rod_torque_limit_nm
    torque = view.tick("torque_nm")
    hit = view.first_true(torque > limit, torque)
    if hit is None:
        return []
    return [
        _Candidate(
            1,
            hit.t_sim_s,
            "operating_point",
            "torque_nm",
            float(np.nanmax(torque)),
            limit,
            "N.m",
            f"Torque acima do limite da biela ({limit:.0f} N·m)",
        )
    ]


def _preignition_family(view: TraceView) -> list[_Candidate]:
    out: list[_Candidate] = []
    iat = view.tick("iat_c")
    if iat.size and not np.isnan(iat).all():
        k = int(np.nanargmax(iat))
        out.append(
            _Candidate(
                0,
                float(view.t[k]),
                "operating_point",
                "iat_c",
                float(iat[k]),
                None,
                "C",
                f"IAT máxima de {float(iat[k]):.0f} °C",
            )
        )
    threshold = view.trace.meta.hot_spot_threshold_c - 30.0
    near = view.first_cylinder_crossing("hot_spot_temp_c", threshold)
    if near is not None:
        out.append(
            _Candidate(
                1,
                near.t_sim_s,
                "combustion",
                "hot_spot_temp_c",
                near.value,
                threshold,
                "C",
                f"Ponto quente perto do limiar no cilindro {near.cylinder}",
                near.cylinder,
            )
        )
    k_pi = view.first_cycle(view.cycle("preignition") > 0.0)
    if k_pi is not None:
        cyl = int(view.cycle("cylinder")[k_pi])
        p_pi = float(view.cycle("p_preignition_kpa")[k_pi])
        out.append(
            _Candidate(
                2,
                float(view.cycle("t_sim_s")[k_pi]),
                "combustion",
                "p_preignition_kpa",
                p_pi,
                view.trace.meta.limits.cylinder_pressure_limit_kpa,
                "kPa",
                f"Pré-ignição no cilindro {cyl} ({p_pi:.0f} kPa), runaway",
                cyl,
            )
        )
    return out


def _overrev_family(view: TraceView, mechanism: str | None) -> list[_Candidate]:
    limits = view.trace.meta.limits
    if mechanism == "turbo_overspeed_burst" and limits.turbo_max_rpm is not None:
        data, limit, name, label = (
            view.tick("turbo_rpm"),
            limits.turbo_max_rpm,
            "turbo_rpm",
            "Turbina",
        )
    else:
        data, limit, name, label = view.tick("rpm"), limits.valve_float_rpm, "rpm", "Rotação"
    hit = view.first_true(data > limit, data)
    if hit is None:
        return []
    return [
        _Candidate(
            1,
            hit.t_sim_s,
            "operating_point",
            name,
            float(np.nanmax(data)),
            limit,
            "rpm",
            f"{label} acima de {limit:.0f} rpm",
        )
    ]


def build_causal_chain(  # noqa: PLR0912
    view: TraceView,
    failure: FailureEvent | None,
    calibration_diff: CalibrationDiff | None,
    *,
    end_description: str = "Fim da puxada por proteção (quase-falha)",
) -> list[CausalLink]:
    """Monta a cadeia (3 a 12 elos, ordem crescente de ``t_sim_s``)."""
    mechanism = None if failure is None else failure.mechanism.value
    family = chain_family(mechanism)
    candidates = _calibration(view, calibration_diff, family)
    if family == "knock":
        map_point = _peak_operating_point(view, "map_kpa", "kPa", "MAP", None)
        if map_point is not None:
            candidates.append(map_point)
        candidates.extend(_knock_family(view))
    elif family == "thermal":
        candidates.extend(_thermal_family(view, mechanism))
    elif family == "rod":
        candidates.extend(_rod_family(view))
    elif family == "preignition":
        candidates.extend(_preignition_family(view))
    else:
        candidates.extend(_overrev_family(view, mechanism))
    component = None if failure is None else failure.component_id
    if family != "preignition":
        candidates.extend(_health_drops(view, component, 5))
    if not any(c.kind == "operating_point" for c in candidates):
        rpm = view.tick("rpm")
        if rpm.size:
            candidates.append(
                _Candidate(
                    1,
                    view.t_f,
                    "operating_point",
                    "rpm",
                    float(rpm[-1]),
                    None,
                    "rpm",
                    f"Ponto de operação: {float(rpm[-1]):.0f} rpm",
                )
            )
    if len(candidates) < 2 and failure is not None:  # noqa: PLR2004
        first = next(
            (
                c.first_damage_t_sim_s
                for c in view.trace.components
                if c.component_id == failure.component_id and c.first_damage_t_sim_s is not None
            ),
            None,
        )
        if first is not None:
            candidates.append(
                _Candidate(
                    5,
                    min(first, view.t_f),
                    "damage",
                    f"health:{failure.component_id}",
                    1.0,
                    None,
                    "health",
                    f"Início do dano em {failure.component_id}",
                )
            )
    candidates = [c for c in candidates if c.t <= view.t_f + _EPS]
    candidates.sort(key=lambda c: (c.t, c.rank))
    candidates = candidates[: MAX_CAUSAL_LINKS - 1]
    if failure is not None:
        tail = _Candidate(
            9,
            failure.t_sim_s,
            "failure",
            failure.component_id,
            failure.health_after,
            0.0,
            "health",
            f"Falha {failure.mode.value} ({failure.mechanism.value}) em {failure.component_id}",
            failure.cylinder,
        )
    else:
        tail = _Candidate(9, view.t_f, "warning", "run_end", view.t_f, None, "s", end_description)
    candidates.append(tail)
    return [
        CausalLink(
            order=i,
            t_sim_s=max(0.0, round(c.t, 6)),
            kind=c.kind,
            cylinder=c.cylinder,
            variable=c.variable[:64],
            value=round(c.value, 6),
            threshold=None if c.threshold is None else round(c.threshold, 6),
            unit=c.unit,
            description=c.description[:240],
        )
        for i, c in enumerate(candidates, start=1)
    ]
