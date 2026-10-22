"""Jornada do Lucas ponta a ponta no laço real (knock-and-failure-model Apêndice D; G-01, G-02).

``DynoSimTask`` (a tarefa do worker de produção) com o ``hatch-20t-gdi`` e a calibração
``oem-stage`` do catálogo, ``ProfiledEcu`` (caminho de torque OEM), ``DamageConfig`` padrão,
E27, ``seed`` 42, 1000 Hz, SAE J1349 e ``operator_protection = false``:

1. ``baseline_pull`` de série: knock ≤ ``light`` e motor intacto.
2. Calibração exagerada (``oem_pressure_target`` 280 kPa abs nas células de carga com
   pressão, ``ignition_base`` +8° em todas as células e limites de torque OEM ×1,5 para o
   caminho de torque não a anular) aplicada por ``calibration.apply``; ``sweep_pull`` em
   4.ª de 2000 a 6300 rpm a 150 rpm/s:
   knock ``severe``, retardo saturado, ``FailureEvent`` catastrófico ``piston_failure``/
   ``knock_erosion`` ou ``rod_failure``/``rod_overload`` e laudo (``damage.trace`` →
   ``build_forensic_report``) com ≥ 3 elos, aviso com ``lead_time_s ≥ 1,0`` e as regras
   ``R-KNOCK-01`` e ``R-LAMBDA-01``.
3. ``engine.restore`` e o acerto corrigido do laudo sobre a calibração de série (Stage 2 do
   RF-40): λ 0,85 com MAP ≥ 150 kPa (o motor frio depois do restauro enriquece e o λ real
   fica em 0,78–0,82, a janela do R-LAMBDA-01), −3° em ``ignition_trim_cyl`` nos cilindros
   com knock (na faixa de rotação dos ciclos com knock), +1° de avanço base acima de
   5500 rpm, pedido/limites de torque da ECU acima da pressão e a pressão alvo limitada por
   rotação (``CORRECTED_BOOST_*``: 226 kPa a 4500 rpm até 292 kPa a 6300 rpm) para o torque
   ficar abaixo dos 420 N·m da biela; ``sweep_pull``: knock ≤ ``light``, EGT pré-turbina
   ≤ 950 °C, torque ≤ 420 N·m, ``intact`` e +65 whp sobre a base.
"""

from __future__ import annotations

import copy
import itertools
from functools import cache
from typing import Any

import pytest
from dyno_helpers import RunOutcome, catalog_fuels, make_task, new_ulid, run_to_result

from simremap.catalog.contracts import VehicleSpec
from simremap.damage.config import DamageConfig
from simremap.damage.forensic.report import build_forensic_report
from simremap.dyno.contracts import DynoRun, RunState
from simremap.dyno.runner import DynoSimTask
from simremap.dyno.trace_codec import decode_trace
from simremap.ecu.calibration import CalibrationContent, compute_content_hash, parse_content

VEHICLE_ID = "hatch-20t-gdi"
CLASS_RANK = {"none": 0, "light": 1, "moderate": 2, "severe": 3}
EXAGGERATED_BOOST_KPA = 280.0
# Acerto corrigido (Stage 2): teto da pressão alvo por rotação (kPa abs). A série cai de
# 222 kPa (5000 rpm) para 198 kPa (6500 rpm); o perfil sobe com a rotação porque o torque na
# biela (420 N·m) limita a 4500–6000 rpm e a potência de pico sai a 6000–6300 rpm.
CORRECTED_BOOST_RPM = (4000.0, 4500.0, 5000.0, 5500.0, 6000.0, 6300.0, 6500.0)
CORRECTED_BOOST_KPA = (225.0, 226.0, 244.0, 260.0, 276.0, 292.0, 296.0)
CORRECTED_LAMBDA = 0.85
CORRECTED_TORQUE_NM = 520.0  # pedido/limites da ECU acima do que a pressão entrega
CORRECTED_OVERBOOST_KPA = 340.0
SWEEP_RATE_RPM_S = 150.0  # rampa da sweep_pull (RF-07: 50–1000 rpm/s)
TORQUE_TABLES = ("torque_request", "torque_limit", "torque_limit_gear")


@cache
def _catalog() -> tuple[VehicleSpec, dict[str, Any]]:
    from simremap.catalog.service import load_catalog

    service = load_catalog()
    payload = service.get_factory_calibration_payload(VEHICLE_ID, "oem-stage")
    assert payload is not None
    return service.get_vehicle(VEHICLE_ID), payload


def _content(payload: dict[str, Any]) -> CalibrationContent:
    return parse_content({**payload, "vehicle_id": VEHICLE_ID, "profile_id": "oem-stage"})


def exaggerated_payload(stock: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(stock)
    tables = payload["tables"]
    for name in TORQUE_TABLES:
        table = tables[name]
        if table["dims"] == 3:
            table["values"] = [[1.5 * v for v in row] for row in table["values"]]
        else:
            table["values"] = [1.5 * v for v in table["values"]]
    pressure = tables["oem_pressure_target"]
    pressure["values"] = [
        [EXAGGERATED_BOOST_KPA if v >= 150.0 else v for v in row] for row in pressure["values"]
    ]
    ignition = tables["ignition_base"]
    ignition["values"] = [[v + 8.0 for v in row] for row in ignition["values"]]
    return payload


def _interp(x: float, xs: tuple[float, ...], ys: tuple[float, ...]) -> float:
    if x <= xs[0]:
        return ys[0]
    for (x0, y0), (x1, y1) in itertools.pairwise(zip(xs, ys, strict=True)):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return ys[-1]


def corrected_payload(
    stock: dict[str, Any], knock_cylinders: list[int], knock_rpm_max: float
) -> dict[str, Any]:
    payload = copy.deepcopy(stock)
    tables = payload["tables"]
    request = tables["torque_request"]
    request["values"] = [[1.4 * v for v in row] for row in request["values"]]
    limit = tables["torque_limit"]
    limit["values"] = [
        max(v, _interp(r, (4250.0, 4750.0, 5250.0), (v, 450.0, CORRECTED_TORQUE_NM)))
        if r >= 4250.0
        else v
        for r, v in zip(limit["x"]["values"], limit["values"], strict=True)
    ]
    gear = tables["torque_limit_gear"]
    gear["values"] = [
        max(v, CORRECTED_TORQUE_NM) if g >= 3 else v
        for g, v in zip(gear["x"]["values"], gear["values"], strict=True)
    ]
    pressure = tables["oem_pressure_target"]
    pressure["values"] = [
        [
            min(v, _interp(r, CORRECTED_BOOST_RPM, CORRECTED_BOOST_KPA))
            for r, v in zip(pressure["x"]["values"], row, strict=True)
        ]
        for row in pressure["values"]
    ]
    lam = tables["lambda_target"]
    lam["values"] = [
        [CORRECTED_LAMBDA if map_kpa >= 150.0 else v for v in row]
        for map_kpa, row in zip(lam["y"]["values"], lam["values"], strict=True)
    ]
    ignition = tables["ignition_base"]
    ignition["values"] = [
        [
            v + _interp(r, (5000.0, 5500.0), (0.0, 1.0))
            for r, v in zip(ignition["x"]["values"], row, strict=True)
        ]
        for row in ignition["values"]
    ]
    payload["strategies"]["boost_control"]["overboost_kpa"] = CORRECTED_OVERBOOST_KPA
    edge = knock_rpm_max + 250.0
    for cylinder in knock_cylinders:
        tables[f"ignition_trim_cyl_{cylinder}"] = {
            "table_id": f"ignition_trim_cyl_{cylinder}",
            "kind": "ignition_trim_cyl",
            "unit": "°",
            "live_tunable": True,
            "cylinder": cylinder,
            "description": "R-KNOCK-01: −3° na região dos ciclos com knock",
            "decimals": 1,
            "dims": 3,
            "x": {"quantity": "rpm", "values": [500.0, edge, edge + 500.0, 8000.0]},
            "y": {"quantity": "map_kpa", "values": [20.0, 400.0]},
            "values": [[-3.0, -3.0, 0.0, 0.0], [-3.0, -3.0, 0.0, 0.0]],
        }
    return payload


def apply(task: DynoSimTask, payload: dict[str, Any], calibration_id: str) -> None:
    content = _content(payload)
    task.handle_command(
        {
            "type": "calibration.apply",
            "request_id": calibration_id,
            "payload_json": content.model_dump_json(),
            "calibration_id": calibration_id,
            "version": 1,
            "content_hash": compute_content_hash(content),
            "mode": "full",
        }
    )


class Probe:
    """Máximos do tick durante ``running``/``coastdown`` (retardo de knock da ECU)."""

    def __init__(self) -> None:
        self.max_retard_deg = 0.0

    def __call__(self, task: DynoSimTask) -> None:
        if task.run_active and task.last_ecu is not None:
            retard = max(task.last_ecu.status.knock_retard_deg)
            self.max_retard_deg = max(self.max_retard_deg, retard)


def knock_events(out: RunOutcome) -> list[dict[str, Any]]:
    return [e["payload"] for e in out.of_type("event.knock")]


def worst_knock(out: RunOutcome) -> str:
    rank = max((CLASS_RANK[k["knock_class"]] for k in knock_events(out)), default=0)
    return next(name for name, value in CLASS_RANK.items() if value == rank)


def run(task: DynoSimTask, run_type: str, probe: Probe | None = None) -> RunOutcome:
    request: dict[str, Any] = {"run_type": run_type}
    if run_type == "sweep_pull":
        request["ramp_rate_rpm_s"] = SWEEP_RATE_RPM_S
    return run_to_result(task, request, run_id=new_ulid(), on_tick=probe, max_s=300.0)


@pytest.fixture(scope="module")
def journey() -> dict[str, Any]:
    vehicle, stock = _catalog()
    task = make_task(
        vehicle=vehicle,
        fuel=catalog_fuels()["e27"],
        calibration=_content(stock),
        calibration_id=f"stock-{VEHICLE_ID}-oem-stage",
        profile_hooks="registry",
        damage_config=DamageConfig(),
        seed=42,
    )
    base = run(task, "baseline_pull")
    apply(task, exaggerated_payload(stock), "lucas-exagerada")
    probe = Probe()
    failed = run(task, "sweep_pull", probe)
    traces = [e["payload"] for e in failed.of_type("damage.trace")]
    task.handle_command({"type": "engine.restore", "request_id": "restore-1"})
    severe_or_moderate = [k for k in knock_events(failed) if CLASS_RANK[k["knock_class"]] >= 2]
    cylinders = sorted({int(k["cylinder"]) for k in severe_or_moderate}) or [1, 2, 3, 4]
    rpm_max = max((float(k["rpm"]) for k in severe_or_moderate), default=4000.0)
    apply(task, corrected_payload(stock, cylinders, rpm_max), "lucas-corrigida")
    corrected = run(task, "sweep_pull")
    return {
        "base": base,
        "failed": failed,
        "traces": traces,
        "probe": probe,
        "corrected": corrected,
        "knock_cylinders": cylinders,
    }


def test_baseline_pull_is_clean(journey: dict[str, Any]) -> None:
    base: RunOutcome = journey["base"]
    assert base.run.state == RunState.COMPLETED
    assert CLASS_RANK[worst_knock(base)] <= CLASS_RANK["light"]
    assert base.result["health"]["intact"] is True
    summary = base.run.summary
    assert summary is not None and 209.0 <= summary.peak_whp <= 231.0


def test_exaggerated_calibration_destroys_the_engine(journey: dict[str, Any]) -> None:
    failed: RunOutcome = journey["failed"]
    assert failed.run.state == RunState.ENGINE_FAILED
    assert worst_knock(failed) == "severe"
    assert journey["probe"].max_retard_deg >= 8.0 - 1e-9  # retardo saturado (max_retard_deg)
    catastrophic = [f for f in failed.result["failures"] if f["catastrophic"]]
    assert len(catastrophic) == 1
    assert (catastrophic[0]["mode"], catastrophic[0]["mechanism"]) in {
        ("piston_failure", "knock_erosion"),
        ("rod_failure", "rod_overload"),
    }
    assert failed.run.summary is not None
    assert failed.run.summary.failure_event_id == catastrophic[0]["failure_event_id"]


def test_forensic_report_explains_the_failure(journey: dict[str, Any]) -> None:
    failed: RunOutcome = journey["failed"]
    base: DynoRun = journey["base"].run
    assert len(journey["traces"]) == 1 and journey["traces"][0]["kind"] == "failure"
    trace = decode_trace(journey["traces"][0]["trace"])
    report = build_forensic_report(trace, failed.run, base, None, "failure")
    assert report.report_kind == "failure" and report.failure_event is not None
    chain = report.causal_chain
    assert len(chain) >= 3 and chain[-1].kind == "failure"
    assert all(link.t_sim_s <= report.failure_event.t_sim_s + 1e-9 for link in chain)
    assert any(w.lead_time_s >= 1.0 for w in report.early_warnings)
    rules = {r.rule_id for r in report.recommendations}
    assert {"R-KNOCK-01", "R-LAMBDA-01"} <= rules


def test_corrected_calibration_survives(journey: dict[str, Any]) -> None:
    corrected: RunOutcome = journey["corrected"]
    assert corrected.run.state == RunState.COMPLETED
    assert CLASS_RANK[worst_knock(corrected)] <= CLASS_RANK["light"]
    summary = corrected.run.summary
    assert summary is not None
    assert summary.egt_max_c <= 950.0
    assert summary.peak_torque_engine_nm <= 420.0
    health = corrected.result["health"]
    assert health["intact"] is True and health["engine_locked"] is False
    assert health["integrity_pct"] == 100.0
    assert not [f for f in corrected.result["failures"] if f["catastrophic"]]


def test_corrected_calibration_gains_65_whp(journey: dict[str, Any]) -> None:
    """RF-40 (persona Lucas): o acerto corrigido ganha ≥ +65 whp sobre a puxada base."""
    base = journey["base"].run.summary
    corrected = journey["corrected"].run.summary
    assert base is not None and corrected is not None
    assert corrected.peak_whp - base.peak_whp >= 65.0, (base.peak_whp, corrected.peak_whp)
