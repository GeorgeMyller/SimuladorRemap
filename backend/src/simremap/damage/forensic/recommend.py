"""Recomendações didáticas e comparação com a calibração da puxada base (RF-25, RF-31).

Regras do Apêndice C.3 (no máximo 8 por laudo, na ordem da tabela). A comparação de
calibração devolve o maior delta (com sinal) por tabela na região visitada rpm × carga.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from simremap.damage.contracts import (
    CalibrationDiff,
    EarlyWarning,
    FailureEvent,
    Recommendation,
    TableDelta,
)
from simremap.damage.forensic.view import TraceView

__all__ = [
    "COMPARED_TABLES",
    "TableGrid",
    "build_recommendations",
    "compute_calibration_diff",
]

COMPARED_TABLES: Final = ("boost_target", "ignition_base", "lambda_target", "ignition_trim_cyl")
TABLE_UNITS: Final = {
    "boost_target": "kPa",
    "ignition_base": "deg",
    "lambda_target": "lambda",
    "ignition_trim_cyl": "deg",
}
MAX_RECOMMENDATIONS: Final = 8
LAMBDA_RICH_MAX: Final = 0.82
LOADED_MAP_KPA: Final = 150.0
BOOST_MARGIN_KPA: Final = 50.0
ROD_TORQUE_TARGET: Final = 0.90
REV_MARGIN_RPM: Final = 200.0
LSPI_RPM_MAX: Final = 3000.0


@dataclass(frozen=True, slots=True)
class TableGrid:
    """Tabela 2D da ECU (linhas = carga, colunas = rpm)."""

    rpm_axis: tuple[float, ...]
    load_axis: tuple[float, ...]
    values: tuple[tuple[float, ...], ...]  # len(load) linhas × len(rpm) colunas


def _region_delta(
    current: TableGrid,
    baseline: TableGrid,
    rpm_range: tuple[float, float],
    load_range: tuple[float, float],
) -> tuple[float, float, float] | None:
    if current.rpm_axis != baseline.rpm_axis or current.load_axis != baseline.load_axis:
        raise ValueError("tabelas com eixos diferentes não são comparáveis")
    cur = np.asarray(current.values, dtype=np.float64)
    base = np.asarray(baseline.values, dtype=np.float64)
    rpm = np.asarray(current.rpm_axis)
    load = np.asarray(current.load_axis)
    cols = np.flatnonzero((rpm >= rpm_range[0]) & (rpm <= rpm_range[1]))
    rows = np.flatnonzero((load >= load_range[0]) & (load <= load_range[1]))
    if cols.size == 0:
        cols = np.array([int(np.argmin(np.abs(rpm - rpm_range[0])))])
    if rows.size == 0:
        rows = np.array([int(np.argmin(np.abs(load - load_range[0])))])
    delta = (cur - base)[np.ix_(rows, cols)]
    flat = int(np.argmax(np.abs(delta)))
    r, c = np.unravel_index(flat, delta.shape)
    return float(delta[r, c]), float(rpm[cols[c]]), float(load[rows[r]])


def compute_calibration_diff(
    baseline_run_id: str,
    baseline_calibration_hash: str,
    tables: Mapping[str, Sequence[tuple[TableGrid, TableGrid]]],
    rpm_range: tuple[float, float],
    load_range: tuple[float, float],
) -> CalibrationDiff:
    """RF-31: maior delta por tabela (``ignition_trim_cyl`` = vários pares por cilindro)."""
    deltas: list[TableDelta] = []
    for table_id in COMPARED_TABLES:
        pairs = tables.get(table_id)
        if not pairs:
            continue
        best: tuple[float, float, float] | None = None
        for current, baseline in pairs:
            found = _region_delta(current, baseline, rpm_range, load_range)
            if found is not None and (best is None or abs(found[0]) > abs(best[0])):
                best = found
        if best is not None:
            deltas.append(
                TableDelta(
                    table_id=table_id,
                    max_delta=round(best[0], 6),
                    unit=TABLE_UNITS[table_id],
                    at_rpm=best[1],
                    at_load=best[2],
                )
            )
    return CalibrationDiff(
        baseline_run_id=baseline_run_id,
        baseline_calibration_hash=baseline_calibration_hash,
        deltas=deltas,
    )


def _region(view: TraceView, mask: np.ndarray) -> str | None:
    rpm = view.cycle("rpm")[mask]
    map_kpa = view.cycle("map_kpa")[mask]
    if rpm.size == 0:
        return None
    return (
        f"rpm {float(rpm.min()):.0f}–{float(rpm.max()):.0f}, MAP ≥ {float(map_kpa.min()):.0f} kPa"
    )


def build_recommendations(
    view: TraceView,
    failure: FailureEvent | None,
    warnings: Sequence[EarlyWarning],
    calibration_diff: CalibrationDiff | None,
) -> list[Recommendation]:
    """Aplica as regras ``R-*`` do Apêndice C.3."""
    trace = view.trace
    limits = trace.meta.limits
    mechanism = None if failure is None else failure.mechanism.value
    signals = {w.signal for w in warnings}
    out: list[Recommendation] = []
    classes = view.cycle("knock_class")
    cylinders = view.cycle("cylinder")
    knock_mask = classes >= 2.0  # noqa: PLR2004 - "moderate"
    knock_cyls = sorted({int(c) for c in cylinders[knock_mask]})
    region = _region(view, knock_mask)
    if knock_cyls:
        out.append(
            Recommendation(
                rule_id="R-KNOCK-01",
                action="Retirar 2–4° em ignition_trim_cyl nos cilindros "
                + ", ".join(map(str, knock_cyls)),
                table_id="ignition_trim_cyl",
                cylinders=knock_cyls,
                value_min=2.0,
                value_max=4.0,
                unit="deg",
                region=region,
                rationale="O knock moderado ou severo indica avanço acima do limite de detonação "
                "nesses cilindros; retirar avanço reduz a pressão e a temperatura da zona "
                "não queimada.",
            )
        )
    if len(knock_cyls) >= 3:  # noqa: PLR2004
        out.append(
            Recommendation(
                rule_id="R-KNOCK-02",
                action="Retirar 2–3° em ignition_base na mesma região",
                table_id="ignition_base",
                cylinders=knock_cyls,
                value_min=2.0,
                value_max=3.0,
                unit="deg",
                region=region,
                rationale="Knock em 3 ou mais cilindros indica que o avanço base é alto demais.",
            )
        )
    lam = view.lambda_series()
    loaded = view.tick("map_kpa") >= LOADED_MAP_KPA
    lean = loaded & (lam > LAMBDA_RICH_MAX)
    if bool(lean.any()):
        out.append(
            Recommendation(
                rule_id="R-LAMBDA-01",
                action="Ajustar lambda_target para 0,78–0,82 com MAP ≥ 150 kPa",
                table_id="lambda_target",
                value_min=0.78,
                value_max=0.82,
                unit="lambda",
                region="MAP ≥ 150 kPa",
                rationale=f"Lambda chegou a {float(np.nanmax(lam[lean])):.2f} em alta carga; "
                "a mistura mais rica arrefece a câmara e afasta o knock e a EGT alta.",
            )
        )
    boost_base = trace.meta.stock_boost_kpa
    boost_excess: float | None = None
    if calibration_diff is not None:
        boost = next((d for d in calibration_diff.deltas if d.table_id == "boost_target"), None)
        boost_excess = None if boost is None else boost.max_delta
    elif boost_base is not None:
        target = view.tick("boost_target_kpa")
        if target.size and not np.isnan(target).all():
            boost_excess = float(np.nanmax(target)) - boost_base
    egt_over = bool((view.tick("egt_collector_c") > limits.egt_limit_c).any())
    if boost_excess is not None and boost_excess > BOOST_MARGIN_KPA and (knock_cyls or egt_over):
        out.append(
            Recommendation(
                rule_id="R-BOOST-01",
                action="Reduzir boost_target em 20–40 kPa até eliminar o knock",
                table_id="boost_target",
                value_min=20.0,
                value_max=40.0,
                unit="kPa",
                rationale=f"O boost alvo está {boost_excess:.0f} kPa acima da base e houve knock "
                "ou EGT acima do limite.",
            )
        )
    if mechanism in ("rod_overload", "rod_instant_bend") or "rod_torque_near_limit" in signals:
        target_nm = ROD_TORQUE_TARGET * limits.rod_torque_limit_nm
        out.append(
            Recommendation(
                rule_id="R-ROD-01",
                action=f"Limitar o torque a no máximo {target_nm:.0f} N·m em torque_request ou "
                "boost_target",
                table_id="torque_request",
                value_max=round(target_nm, 3),
                unit="N.m",
                rationale="O torque chegou perto ou acima do limite estrutural da biela.",
            )
        )
    if mechanism in ("turbine_creep", "exhaust_valve_burn"):
        out.append(
            Recommendation(
                rule_id="R-EGT-01",
                action="Enriquecer lambda para 0,78–0,82 e trazer o avanço para até 4° do MBT",
                table_id="lambda_target",
                value_min=0.78,
                value_max=0.82,
                unit="lambda",
                rationale="A EGT ficou acima do limite tempo suficiente para fluência do material.",
            )
        )
    preignition = view.cycle("preignition")
    if mechanism == "hot_spot_preignition" or bool((preignition == 1.0).any()):
        out.append(
            Recommendation(
                rule_id="R-PI-01",
                action="Baixar a IAT (intercooler), retirar 3–5° e reduzir a carga com IAT ≥ 60 °C",
                table_id="ignition_base",
                value_min=3.0,
                value_max=5.0,
                unit="deg",
                region="IAT ≥ 60 °C",
                rationale="O ponto quente passou do limiar de pré-ignição do combustível.",
            )
        )
    if mechanism == "lspi" or bool((preignition == 2.0).any()):  # noqa: PLR2004
        out.append(
            Recommendation(
                rule_id="R-LSPI-01",
                action="Limitar boost_target abaixo de 3000 rpm para IMEP < 1500 kPa",
                table_id="boost_target",
                value_max=1500.0,
                unit="kPa",
                region=f"rpm < {LSPI_RPM_MAX:.0f}",
                rationale="Carga alta em rotação baixa num motor GDI provoca LSPI.",
            )
        )
    overrev = mechanism in ("valve_piston_contact", "bearing_spin") or bool(
        (view.tick("rpm") > limits.max_rpm).any()
    )
    if overrev:
        out.append(
            Recommendation(
                rule_id="R-REV-01",
                action="Baixar o limitador para no máximo "
                f"{limits.max_rpm - REV_MARGIN_RPM:.0f} rpm",
                table_id="rev_limiter",
                value_max=limits.max_rpm - REV_MARGIN_RPM,
                unit="rpm",
                rationale="A rotação passou do máximo mecânico do motor.",
            )
        )
    return out[:MAX_RECOMMENDATIONS]
