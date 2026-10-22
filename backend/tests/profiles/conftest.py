"""Fábricas partilhadas pelos testes do ecu-profiles.

- ``catalog``/``vehicle``: catálogo real (4 veículos) e ``VehicleSpec`` por id;
- ``oem_payload``/``oem_content``: calibração de série ``oem-stage`` do catálogo com o
  ``knock_threshold`` convertido para a escala 0–1 do ecu-core (D-BUS-05; o ficheiro do
  catálogo ainda usa 0–10 e falha a validação do ecu-core);
- ``sensors``: ``SensorReadings`` válido com overrides;
- ``FakeSessionPort``: porta da sessão do dyno-bench em memória (swap com ``ack``);
- ``api``: cliente HTTP com a porta instalada e a calibração OEM de série no banco.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService, get_catalog
from simremap.ecu.calibration import CalibrationContent, CalibrationMetadata, parse_content
from simremap.ecu.repository import CalibrationRepository
from simremap.physics.contracts import SensorReadings
from simremap.profiles.session_port import EcuSessionInfo, EcuSwapCommand

CATALOG_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "simremap" / "catalog" / "data" / "vehicles"
)
SESSION = "0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c"
SensorFactory = Callable[..., SensorReadings]


def fixed_payload(vehicle_id: str, profile_id: str = "oem-stage") -> dict[str, Any]:
    path = CATALOG_DIR / vehicle_id / "calibrations" / f"{profile_id}.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    kt = data["tables"].get("knock_threshold")
    if kt is not None and max(kt["values"]) > 1.0:
        kt["values"] = [min(v / 10.0, 1.0) for v in kt["values"]]
    return data


def content_from(payload: dict[str, Any], vehicle_id: str, profile_id: str) -> CalibrationContent:
    return parse_content({**payload, "vehicle_id": vehicle_id, "profile_id": profile_id})


@pytest.fixture(scope="session")
def catalog() -> CatalogService:
    return get_catalog()


@pytest.fixture
def vehicle(catalog: CatalogService) -> Callable[[str], VehicleSpec]:
    return catalog.get_vehicle


@pytest.fixture
def oem_payload() -> Callable[[str], dict[str, Any]]:
    def make(vehicle_id: str = "hatch-20t-gdi") -> dict[str, Any]:
        return copy.deepcopy(fixed_payload(vehicle_id))

    return make


@pytest.fixture
def oem_content() -> Callable[..., CalibrationContent]:
    def make(vehicle_id: str = "hatch-20t-gdi", **params: Any) -> CalibrationContent:
        data = fixed_payload(vehicle_id)
        data["profile_params"] = {**data.get("profile_params", {}), **params}
        return content_from(data, vehicle_id, "oem-stage")

    return make


SENSOR_DEFAULTS: dict[str, Any] = {
    "t_sim_s": 1.0,
    "tick": 1000,
    "rpm": 3000.0,
    "crank_angle_deg": 0.0,
    "cam_intake_deg": 0.0,
    "cam_exhaust_deg": 0.0,
    "map_kpa": 100.0,
    "baro_kpa": 101.3,
    "boost_pre_throttle_kpa": 100.0,
    "iat_c": 40.0,
    "ect_c": 90.0,
    "oil_temp_c": 95.0,
    "tps_pct": 100.0,
    "lambda_measured": 0.85,
    "egt_collector_c": 750.0,
    "fuel_pressure_kpa": 300.0,
    "battery_v": 14.0,
    "pedal_pct": 100.0,
    "gear": 3,
    "oil_pressure_kpa": 400.0,
}


@pytest.fixture
def sensors() -> SensorFactory:
    def make(n_cyl: int = 4, **over: Any) -> SensorReadings:
        data = {
            **SENSOR_DEFAULTS,
            "egt_c": [750.0] * n_cyl,
            "knock_sensor_v": [0.0] * n_cyl,
            "knock_intensity": [0.0] * n_cyl,
        }
        data.update(over)
        return SensorReadings(**data)

    return make


@dataclass
class FakeSessionPort:
    """Porta do dyno-bench em memória: o ``ack`` do ``ecu.swap`` muda o perfil da sessão."""

    sessions: dict[str, EcuSessionInfo] = field(default_factory=dict)
    commands: list[EcuSwapCommand] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    hang: bool = False
    t_sim_s: float = 12.5

    def add(self, vehicle_id: str, profile_id: str = "oem-stage", **extra: Any) -> str:
        session_id = str(extra.pop("session_id", SESSION))
        self.sessions[session_id] = EcuSessionInfo(
            session_id=session_id, vehicle_id=vehicle_id, profile_id=profile_id, **extra
        )
        return session_id

    def set(self, session_id: str, **changes: Any) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], **changes)

    async def get_session(self, session_id: str) -> EcuSessionInfo | None:
        return self.sessions.get(session_id)

    async def swap_ecu(self, session_id: str, command: EcuSwapCommand) -> float:
        self.commands.append(command)
        if self.hang:
            await asyncio.sleep(5)
        self.set(session_id, profile_id=command.profile_id)
        return self.t_sim_s

    async def cancel_swap(self, session_id: str, request_id: str) -> None:
        self.cancelled.append(request_id)


@dataclass
class Api:
    client: httpx.AsyncClient
    app: FastAPI
    port: FakeSessionPort
    maker: async_sessionmaker[AsyncSession]

    def url(self, path: str, session_id: str = SESSION) -> str:
        return f"/api/v1/sessions/{session_id}/ecu/{path}"


async def seed_oem(maker: async_sessionmaker[AsyncSession], vehicle_id: str) -> str:
    """Grava a calibração OEM de série (``stock-<vehicle>-oem-stage``) se faltar."""
    cal_id = f"stock-{vehicle_id}-oem-stage"
    payload = fixed_payload(vehicle_id)
    async with maker() as session:
        repo = CalibrationRepository(session)
        if not await repo.exists(cal_id):
            meta = CalibrationMetadata.model_validate(
                {**payload["metadata"], "source": "oem_stock"}
            )
            await repo.create(content_from(payload, vehicle_id, "oem-stage"), meta, cal_id)
    return cal_id


@pytest.fixture
async def api(app: FastAPI, client: httpx.AsyncClient) -> AsyncIterator[Api]:
    port = FakeSessionPort()
    app.state.profiles_session_port = port
    maker: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    for vid in ("classic-20t-swap", "hatch-20t-gdi"):
        await seed_oem(maker, vid)
    yield Api(client=client, app=app, port=port, maker=maker)


def classic_base(**over: Any) -> dict[str, Any]:
    """Base completa do Rodrigo pela ficha do ``classic-20t-swap`` (Apêndice F, passo 3)."""
    base: dict[str, Any] = {
        "trigger": {"wheel": "60-2", "tdc_offset_deg": 90.0, "firing_order": [1, 3, 4, 2]},
        "injectors": {
            "flow_cc_min": 2000.0,
            "dead_time_v": [8.0, 10.0, 12.0, 14.0, 16.0],
            "dead_time_ms": [1.6, 1.2, 0.95, 0.8, 0.7],
        },
        "fuel": {"fuel_id": "e100", "afr_stoich": 9.0, "density_g_cc": 0.789},
        "sensors": {"map": {"min_kpa": 20.0, "max_kpa": 400.0}, "wideband": {}},
        "protection": {
            "rev_limit_rpm": 7200.0,
            "overspeed_rpm": 7500.0,
            "overboost_kpa": 260.0,
            "egt_max_c": 900.0,
        },
    }
    base.update(over)
    return base


@pytest.fixture
def make_content() -> Callable[[dict[str, Any], str, str], CalibrationContent]:
    return content_from


@pytest.fixture
def base_payload() -> Callable[..., dict[str, Any]]:
    return classic_base
