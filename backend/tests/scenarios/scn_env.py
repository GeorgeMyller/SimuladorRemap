"""Ambiente de estação dos testes dos cenários (``ScnEnv``) partilhado com ``tests/integration``.

``make_station`` cria a app real com as portas falsas e banco próprio; ``open_station`` liga o
lifespan e devolve o ``ScnEnv`` com o cliente httpx.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from scn_helpers import FakeCalibrations, FakeSimulation, RunSpec, fake_vehicles

from simremap.api.main import create_app
from simremap.dyno.contracts import DynoRunRequest, RunType


@dataclass
class ScnEnv:
    app: FastAPI
    client: httpx.AsyncClient
    sim: FakeSimulation
    cals: FakeCalibrations

    @property
    def services(self) -> Any:
        return self.app.state.scenarios

    async def profile(self, nickname: str, role: str = "student") -> dict[str, str]:
        resp = await self.client.post("/api/v1/profiles", json={"nickname": nickname, "role": role})
        assert resp.status_code == 201, resp.text
        return {"X-Player-Profile-Id": resp.json()["profile_id"]}

    async def drain(self) -> None:
        await self.services.attempts.drain()
        await self.services.replay.drain()

    async def start(self, scenario_id: str, headers: dict[str, str]) -> dict[str, Any]:
        resp = await self.client.post(f"/api/v1/scenarios/{scenario_id}/attempts", headers=headers)
        assert resp.status_code == 201, resp.text
        await self.drain()
        return await self.attempt(resp.json()["attempt_id"], headers)

    async def attempt(self, attempt_id: str, headers: dict[str, str]) -> dict[str, Any]:
        resp = await self.client.get(f"/api/v1/attempts/{attempt_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data: dict[str, Any] = resp.json()
        return data

    def tune(
        self,
        attempt: dict[str, Any],
        spec: RunSpec,
        marker: str = "tuned",
        *,
        profile_id: str | None = None,
    ) -> str:
        """Nova versão da calibração da tentativa com o comportamento ``spec``, aplicada."""
        record = self.cals.new_version(attempt["calibration_id"], marker)
        self.sim.behaviour[record.content_hash] = spec
        self.sim.apply(
            attempt["session_id"],
            attempt["calibration_id"],
            record.content_hash,
            profile_id=profile_id,
        )
        return record.content_hash

    async def pull(
        self, attempt: dict[str, Any], run_type: str = "sweep_pull", **request: Any
    ) -> str:
        run = await self.sim.start_run(
            attempt["session_id"], DynoRunRequest(run_type=RunType(run_type), **request)
        )
        return run.run_id

    async def submit(
        self, attempt: dict[str, Any], headers: dict[str, str], **body: Any
    ) -> dict[str, Any]:
        payload = {"calibration_id": attempt["calibration_id"], **body}
        resp = await self.client.post(
            f"/api/v1/attempts/{attempt['attempt_id']}/submit", headers=headers, json=payload
        )
        assert resp.status_code == 202, resp.text
        await self.drain()
        ev = await self.client.get(
            f"/api/v1/attempts/{attempt['attempt_id']}/evaluation", headers=headers
        )
        assert ev.status_code == 200, ev.text
        data: dict[str, Any] = ev.json()
        return data


def make_station(settings_factory: Callable[..., Any], tmp_path: Path, name: str) -> FastAPI:
    db = tmp_path / f"{name}.db"
    app = create_app(
        settings_factory(
            database_url=f"sqlite+aiosqlite:///{db.as_posix()}", data_dir=tmp_path / name
        )
    )
    cals = FakeCalibrations()
    app.state.scenarios_calibration_port = cals
    app.state.scenarios_sim_port = FakeSimulation(cals)
    app.state.scenarios_vehicle_lookup = fake_vehicles
    return app


@asynccontextmanager
async def open_station(app: FastAPI) -> AsyncIterator[ScnEnv]:
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=30) as manager:
        sim: FakeSimulation = app.state.scenarios_sim_port
        sim.audit = app.state.scenarios.audit
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield ScnEnv(app, client, sim, app.state.scenarios_calibration_port)
