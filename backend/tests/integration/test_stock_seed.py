"""Arranque da API com o catálogo real: seed das calibrações de série (T421; data-model 6.3).

Com ``knock_threshold`` na escala 0–1 (D-BUS-05) as 5 calibrações de fábrica do catálogo
(4 ``oem-stage`` + o mapa ``ft-pro`` do ``classic-20t-swap``) passam a validação do
ecu-core e são materializadas no arranque; os routers do Sprint 2 estão todos registados.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from asgi_lifespan import LifespanManager

from simremap.api.main import create_app
from simremap.api.registry import COMPONENT_ROUTER_MODULES

STOCK_IDS = {
    "stock-hatch-20t-gdi-oem-stage",
    "stock-coupe-30t-i6-oem-stage",
    "stock-classic-20t-swap-oem-stage",
    "stock-muscle-v8-sc-oem-stage",
    "stock-classic-20t-swap-ft-pro",
}


async def test_startup_seeds_all_factory_calibrations(settings_factory: Callable[..., Any]) -> None:
    for module in (
        "simremap.catalog.router",
        "simremap.dyno.router",
        "simremap.damage.router",
        "simremap.ecu.router",
        "simremap.profiles.router",
    ):
        assert module in COMPONENT_ROUTER_MODULES
    app = create_app(settings_factory())
    async with LifespanManager(app, startup_timeout=60) as manager:
        report = app.state.ecu_seed_report
        assert set(report.created) == STOCK_IDS and not report.invalid
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            page = (await client.get("/api/v1/calibrations", params={"limit": 50})).json()
            hatch = (await client.get("/api/v1/calibrations/stock-hatch-20t-gdi-oem-stage")).json()
    assert {item["calibration_id"] for item in page["items"]} >= STOCK_IDS
    assert hatch["metadata"]["source"] == "oem_stock" and hatch["profile_id"] == "oem-stage"
    threshold = hatch["tables"]["knock_threshold"]["values"]
    assert 0.0 < min(threshold) <= max(threshold) <= 1.0
