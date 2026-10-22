"""Auxiliares dos testes do dyno-bench (importados por ``sys.path`` nos conftest).

- ``fixture_hatch()``: ``VehicleSpec`` do ``hatch-20t-gdi`` calibrado da fixture da física
  (``tests/physics/conftest.py``: 220 whp / 350 N·m ±2,7 % em regime permanente). Os testes
  com o catálogo real (``ProfiledEcu`` e ``DamageConfig`` padrão) estão em
  ``test_acceptance_catalog.py`` e ``tests/integration/test_journey_*.py``.
- ``stock_content()``: calibração de série afinada para essa física
  (``data/hatch_stock_tuned.json``; ver ``metadata.description``).
- ``INTEGRATION_DAMAGE``/``MECHANICAL_DAMAGE``: ``DamageConfig`` reduzidos usados pelos
  testes do laço com a fixture (a fixture mantém o avanço antigo de série, com p_max ≈ 117 bar
  e força na biela acima dos 52 kN do catálogo); ``MECHANICAL_DAMAGE`` também retira
  ``thermal`` (puxadas completas com coastdown).
- ``make_task``/``run_to_result``: ``DynoSimTask`` sem worker (passos síncronos).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import orjson

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.catalog.errors import FuelNotAllowed, FuelNotFound, VehicleNotFound
from simremap.damage.config import DamageConfig
from simremap.dyno.assembly import DynoInitPayload
from simremap.dyno.contracts import DynoRun
from simremap.dyno.runner import DynoSimTask
from simremap.dyno.session import ResolvedCalibration
from simremap.ecu.calibration import CalibrationContent, compute_content_hash, parse_content

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent
VEHICLE_ID = "hatch-20t-gdi"
STOCK_ID = "stock-hatch-20t-gdi-oem-stage"
SESSION_ID = "0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c"
RUN_ID = "01JAB0000000000000000000AB"

INTEGRATION_DAMAGE = DamageConfig(
    features=("thermal", "mechanical", "forensic", "spectrum", "damage_off")
)
MECHANICAL_DAMAGE = DamageConfig(features=("mechanical", "forensic", "spectrum", "damage_off"))


@cache
def _physics_fixtures() -> Any:
    path = TESTS / "physics" / "conftest.py"
    spec = importlib.util.spec_from_file_location("dyno_physics_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@cache
def fixture_hatch() -> VehicleSpec:
    vehicle: VehicleSpec = _physics_fixtures().build_hatch()
    return vehicle


@cache
def catalog_fuels() -> dict[str, FuelSpec]:
    from simremap.catalog.service import load_catalog

    service = load_catalog(allow_drafts=True)
    return {fid: service.get_fuel(fid) for fid in ("e27", "e100", "podium", "e0")}


def stock_payload() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        (HERE / "data" / "hatch_stock_tuned.json").read_text(encoding="utf-8")
    )
    raw.pop("metadata", None)
    return raw


@cache
def stock_content() -> CalibrationContent:
    return parse_content({**stock_payload(), "vehicle_id": VEHICLE_ID, "profile_id": "oem-stage"})


def modified_content(
    *, boost_kpa: float | None = None, ignition_offset_deg: float = 0.0
) -> CalibrationContent:
    """Calibração "exagerada": alvo de boost fixo a plena carga e avanço somado."""
    payload = stock_payload()
    tables = payload["tables"]
    if boost_kpa is not None:
        bt = tables["boost_target"]
        bt["values"] = [
            [boost_kpa if tps >= 80 else value for value in row]
            for tps, row in zip(bt["y"]["values"], bt["values"], strict=True)
        ]
        payload["strategies"]["boost_control"]["overboost_kpa"] = max(boost_kpa + 60.0, 260.0)
    if ignition_offset_deg:
        ig = tables["ignition_base"]
        ig["values"] = [[v + ignition_offset_deg for v in row] for row in ig["values"]]
    return parse_content({**payload, "vehicle_id": VEHICLE_ID, "profile_id": "oem-stage"})


def resolved(content: CalibrationContent, calibration_id: str = STOCK_ID) -> ResolvedCalibration:
    return ResolvedCalibration(
        calibration_id=calibration_id,
        version=1,
        vehicle_id=VEHICLE_ID,
        profile_id="oem-stage",
        content=content,
        content_hash=compute_content_hash(content),
    )


def make_payload(**over: Any) -> DynoInitPayload:
    content: CalibrationContent = over.pop("calibration", None) or stock_content()
    vehicle = over.pop("vehicle", None) or fixture_hatch()
    fuel = over.pop("fuel", None) or catalog_fuels()[vehicle.stock_fuel_id]
    data: dict[str, Any] = {
        "session_id": SESSION_ID,
        "seed": 7,
        "sim_hz": 1000,
        "vehicle": vehicle,
        "fuel": fuel,
        "calibration": content,
        "calibration_id": STOCK_ID,
        "calibration_hash": compute_content_hash(content),
        "profile_hooks": "null",
        "damage_config": MECHANICAL_DAMAGE,
    }
    data.update(over)
    return DynoInitPayload(**data)


def make_task(**over: Any) -> DynoSimTask:
    task = DynoSimTask()
    task.setup(make_payload(**over).model_dump_json().encode("utf-8"))
    return task


@dataclass
class RunOutcome:
    run: DynoRun
    envelopes: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.envelopes if e["type"] == kind]

    @property
    def states(self) -> list[str]:
        return [e["payload"]["state"] for e in self.of_type("run.state")]


def drain(task: DynoSimTask) -> list[dict[str, Any]]:
    return [orjson.loads(raw) for raw in task.drain_outputs()]


def start_run(task: DynoSimTask, request: dict[str, Any], run_id: str = RUN_ID) -> None:
    task.handle_command({"type": "run.start", "run_id": run_id, "request": request})


def run_to_result(
    task: DynoSimTask,
    request: dict[str, Any] | None = None,
    *,
    run_id: str | None = None,
    max_s: float = 200.0,
    on_tick: Any = None,
) -> RunOutcome:
    """Inicia (se ``request``) e avança até ao ``run.result``."""
    envelopes: list[dict[str, Any]] = []
    if request is not None:
        start_run(task, request, run_id or new_ulid())
    for _ in range(round(max_s * task.sim_hz)):
        task.step()
        if on_tick is not None:
            on_tick(task)
        for env in drain(task):
            envelopes.append(env)
            if env["type"] == "run.result":
                run = DynoRun.model_validate(env["payload"]["run"])
                return RunOutcome(run, envelopes, env["payload"])
    raise AssertionError("a puxada não terminou no tempo simulado previsto")


_COUNTER = [0]


def new_ulid() -> str:
    _COUNTER[0] += 1
    return f"01JAB{_COUNTER[0]:021d}"


def new_session_id() -> str:
    return uuid.uuid4().hex


class FixtureVehicleSource:
    """Catálogo de teste: só o hatch calibrado (os outros devolvem 404)."""

    def __init__(self, vehicle: VehicleSpec | None = None) -> None:
        self.vehicle = vehicle or fixture_hatch()

    def vehicle_for_session(self, vehicle_id: str) -> VehicleSpec:
        if vehicle_id != self.vehicle.vehicle_id:
            raise VehicleNotFound(f"O veículo {vehicle_id} não existe.", vehicle_id=vehicle_id)
        return self.vehicle

    def fuel_for_vehicle(self, vehicle_id: str, fuel_id: str) -> FuelSpec:
        fuels = catalog_fuels()
        if fuel_id not in fuels:
            raise FuelNotFound(f"O combustível {fuel_id} não existe.", fuel_id=fuel_id)
        if fuel_id not in self.vehicle.allowed_fuel_ids:
            raise FuelNotAllowed(
                f"O combustível {fuel_id} não é permitido no veículo {vehicle_id}.",
                allowed_fuel_ids=list(self.vehicle.allowed_fuel_ids),
            )
        return fuels[fuel_id]

    def catalog_sha256(self) -> str:
        return "a" * 64

    def factory_calibration(self, vehicle_id: str, profile_id: str) -> dict[str, Any] | None:
        return None


class FixtureCalibrationSource:
    """Calibrações em memória (``calibration_id`` → conteúdo)."""

    def __init__(self) -> None:
        self.items: dict[str, ResolvedCalibration] = {STOCK_ID: resolved(stock_content())}

    def add(
        self, calibration_id: str, content: CalibrationContent, vehicle_id: str = VEHICLE_ID
    ) -> None:
        item = resolved(content, calibration_id)
        if vehicle_id != VEHICLE_ID:
            item = ResolvedCalibration(
                calibration_id=calibration_id,
                version=1,
                vehicle_id=vehicle_id,
                profile_id="oem-stage",
                content=content,
                content_hash=item.content_hash,
            )
        self.items[calibration_id] = item

    async def resolve(
        self, calibration_id: str, vehicle_id: str, profile_id: str
    ) -> ResolvedCalibration | None:
        return self.items.get(calibration_id)


def make_dyno_app(settings: Any, calibrations: FixtureCalibrationSource) -> Any:
    """``create_app`` com as fontes de teste e opções do laço para testes REST."""
    from simremap.api.main import create_app
    from simremap.ecu.ports import NullHooksProvider

    app = create_app(settings)
    # Calibração genérica (boost_target/ignition_base por MAP) com a ECU do Sprint 2 sobre a
    # física da fixture; o caminho de torque OEM com o catálogo real é testado em
    # test_acceptance_catalog.py (217 whp / 346 N·m no hatch).
    app.state.ecu_profile_hooks = NullHooksProvider()
    app.state.dyno_vehicle_source = FixtureVehicleSource()
    app.state.dyno_calibration_source = calibrations
    app.state.dyno_task_options = {
        "profile_hooks": "null",
        "damage_config": MECHANICAL_DAMAGE,
        "steps_per_tick": 10,
    }
    return app
