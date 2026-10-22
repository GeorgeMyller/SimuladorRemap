"""Aceite com o catálogo real e o modelo de dano completo (integração física × ECU × dano).

- ``test_g01_catalog_hatch_baseline`` (G-01): ``hatch-20t-gdi`` e calibração ``oem-stage`` do
  catálogo pelo ``ProfiledEcu`` (caminho de torque OEM) com o ``DamageConfig`` padrão:
  220 whp ± 5 % e 350 N·m ± 5 % no motor, SAE J1349.
- ``test_prd_stock_numbers``: os 4 veículos de série pelo laço completo dentro de ± 5 % da
  potência de série do PRD (coupé 340, clássico 318,9 = pico da curva de série dentro da faixa
  300–600 do PRD, V8 460 whp). O V8 (650 N·m) é medido em 5.ª (1:1): em 4.ª a inércia do
  conjunto absorve ~6 % na puxada inercial (RF-05 mede pelo rolo, como num rolo real).
- ``test_stock_engines_survive_full_damage_model``: ``baseline_pull`` e ``multi_pull`` de
  série nos 4 veículos sem knock acima de ``light`` e com saúde ≥ 0,999 (knock-and-failure
  G-02 aplicado à série).
- ``test_full_damage_model_keeps_stock_engine_alive``: o hatch da fixture da física com a
  calibração afinada dos testes do dyno completa a puxada com o ``DamageConfig`` padrão sem
  falha catastrófica (a fixture mantém o avanço antigo: p_max ≈ 117 bar e alguma sobrecarga
  de biela contra os 52 kN; a série do catálogo é que tem de ficar intacta).
"""

from __future__ import annotations

from functools import cache
from typing import Any

import pytest
from dyno_helpers import RunOutcome, catalog_fuels, make_task, run_to_result

from simremap.catalog.contracts import VehicleSpec
from simremap.damage.config import DamageConfig
from simremap.dyno.contracts import RunState
from simremap.dyno.runner import DynoSimTask
from simremap.ecu.calibration import CalibrationContent, parse_content

CLASS_RANK = {"none": 0, "light": 1, "moderate": 2, "severe": 3}
PRD_STOCK: dict[str, tuple[int, float]] = {
    # vehicle_id: (marcha da puxada base, whp de série)
    "hatch-20t-gdi": (4, 220.0),
    "coupe-30t-i6": (4, 340.0),
    "classic-20t-swap": (4, 318.9),
    "muscle-v8-sc": (5, 460.0),
}


@cache
def catalog_inputs(vehicle_id: str) -> tuple[VehicleSpec, CalibrationContent]:
    from simremap.catalog.service import load_catalog

    service = load_catalog()
    vehicle = service.get_vehicle(vehicle_id)
    assert vehicle.validation_status == "validated"
    payload = service.get_factory_calibration_payload(vehicle_id, "oem-stage")
    assert payload is not None
    content = parse_content({**payload, "vehicle_id": vehicle_id, "profile_id": "oem-stage"})
    return vehicle, content


def catalog_task(vehicle_id: str, **over: Any) -> DynoSimTask:
    vehicle, content = catalog_inputs(vehicle_id)
    return make_task(
        vehicle=vehicle,
        fuel=catalog_fuels()[vehicle.stock_fuel_id],
        calibration=content,
        calibration_id=f"stock-{vehicle_id}-oem-stage",
        profile_hooks="registry",
        damage_config=DamageConfig(),
        **over,
    )


def worst_knock(out: RunOutcome) -> int:
    classes = [CLASS_RANK[e["payload"]["knock_class"]] for e in out.of_type("event.knock")]
    return max(classes, default=0)


def assert_intact(out: RunOutcome) -> None:
    health = out.result["health"]
    assert health["intact"] is True and health["min_health"] >= 0.999
    assert not out.result["failures"]
    assert worst_knock(out) <= CLASS_RANK["light"]


def test_g01_catalog_hatch_baseline() -> None:
    out = run_to_result(catalog_task("hatch-20t-gdi"), {"run_type": "baseline_pull"})
    assert out.run.state == RunState.COMPLETED
    summary = out.run.summary
    assert summary is not None
    assert 209.0 <= summary.peak_whp <= 231.0
    assert 332.5 <= summary.peak_torque_engine_nm <= 367.5
    assert_intact(out)


@pytest.mark.parametrize("vehicle_id", sorted(PRD_STOCK))
def test_prd_stock_numbers(vehicle_id: str) -> None:
    gear, whp = PRD_STOCK[vehicle_id]
    out = run_to_result(catalog_task(vehicle_id), {"run_type": "baseline_pull", "gear": gear})
    assert out.run.state == RunState.COMPLETED
    summary = out.run.summary
    assert summary is not None
    assert 0.95 * whp <= summary.peak_whp <= 1.05 * whp
    assert_intact(out)


@pytest.mark.parametrize("vehicle_id", sorted(PRD_STOCK))
def test_stock_engines_survive_full_damage_model(vehicle_id: str) -> None:
    task = catalog_task(vehicle_id, seed=42)
    gear = PRD_STOCK[vehicle_id][0]
    base = run_to_result(task, {"run_type": "baseline_pull", "gear": gear})
    assert base.run.state == RunState.COMPLETED
    assert_intact(base)
    multi = run_to_result(task, {"run_type": "multi_pull", "gear": gear}, max_s=600.0)
    assert multi.run.state == RunState.COMPLETED
    assert len(multi.run.pulls) == 3
    assert_intact(multi)


def test_full_damage_model_keeps_stock_engine_alive() -> None:
    out = run_to_result(make_task(damage_config=DamageConfig()), {"run_type": "baseline_pull"})
    assert out.run.state == RunState.COMPLETED
    assert not [f for f in out.result["failures"] if f["catastrophic"]]
