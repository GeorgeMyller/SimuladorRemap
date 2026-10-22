"""Materialização idempotente das calibrações de série (data-model 6.3; catalog RF-20; T314)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from asgi_lifespan import LifespanManager

from simremap.api.main import create_app
from simremap.ecu.ports import NullHooksProvider
from simremap.ecu.repository import CalibrationRepository
from simremap.ecu.seed_stock import (
    StockCalibrationSource,
    discover_stock_sources,
    seed_stock_calibrations,
)


def _file_payload(tb: Any, ve: float = 90.0) -> dict[str, Any]:
    tables = tb.base_tables()
    tables["ve"] = tb.t3("ve", "ve", "%", ve)
    return {
        "fuel_model": {"mode": "speed_density_ve"},
        "tables": tables,
        "strategies": {"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6800.0}},
        "metadata": {"name": "Série hatch", "source": "oem_stock"},
    }


def _write_catalog(root: Path, tb: Any, ve: float = 90.0) -> None:
    path = root / "vehicles" / "hatch-20t-gdi" / "calibrations" / "oem-stage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_file_payload(tb, ve)), encoding="utf-8")
    bad = root / "vehicles" / "sedan-x" / "calibrations" / "ft-pro.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{nao json", encoding="utf-8")
    lst = root / "vehicles" / "sedan-x" / "calibrations" / "m1-race.json"
    lst.write_text("[]", encoding="utf-8")


def test_discover_stock_sources(tmp_path: Path, tb: Any) -> None:
    assert discover_stock_sources(tmp_path / "nada") == []
    _write_catalog(tmp_path, tb)
    sources = discover_stock_sources(tmp_path)
    assert [(s.vehicle_id, s.profile_id) for s in sources] == [("hatch-20t-gdi", "oem-stage")]
    assert sources[0].calibration_id == "stock-hatch-20t-gdi-oem-stage"


async def test_seed_is_idempotent_and_versions_on_change(
    settings_factory: Any, tb: Any, tmp_path: Path
) -> None:
    app = create_app(settings_factory())
    app.state.ecu_stock_sources = []  # sem o seed do catálogo real no arranque
    async with LifespanManager(app):
        maker = app.state.sessionmaker
        src = [StockCalibrationSource("hatch-20t-gdi", "oem-stage", _file_payload(tb))]
        first = await seed_stock_calibrations(maker, src)
        assert first.created == ["stock-hatch-20t-gdi-oem-stage"]
        again = await seed_stock_calibrations(maker, src)
        assert again.unchanged == ["stock-hatch-20t-gdi-oem-stage"] and not again.created
        changed = [StockCalibrationSource("hatch-20t-gdi", "oem-stage", _file_payload(tb, ve=85.0))]
        upd = await seed_stock_calibrations(maker, changed)
        assert upd.updated == ["stock-hatch-20t-gdi-oem-stage"]
        bad_payload = _file_payload(tb)
        bad_payload["tables"]["ve"]["unit"] = "ms"
        invalid = await seed_stock_calibrations(
            maker, [StockCalibrationSource("sedan-x", "ft-pro", bad_payload)]
        )
        assert invalid.invalid == ["stock-sedan-x-ft-pro"]
        async with maker() as session:
            repo = CalibrationRepository(session)
            cal = await repo.get("stock-hatch-20t-gdi-oem-stage")
            versions = await repo.versions("stock-hatch-20t-gdi-oem-stage")
            assert not await repo.exists("stock-sedan-x-ft-pro")
    assert cal.version == 2 and cal.metadata.source == "oem_stock"
    assert cal.profile_id.value == "oem-stage" and cal.vehicle_id == "hatch-20t-gdi"
    assert [v.source for v in versions] == ["oem_stock", "oem_stock"]


async def test_router_lifespan_seeds_stock(settings_factory: Any, tb: Any, tmp_path: Path) -> None:
    app = create_app(settings_factory())
    # calibração ``speed_density_ve`` de fixture: regras do ecu-core sem a matriz de perfis
    app.state.ecu_profile_hooks = NullHooksProvider()
    app.state.ecu_stock_sources = [
        StockCalibrationSource("hatch-20t-gdi", "oem-stage", _file_payload(tb))
    ]
    async with LifespanManager(app) as manager:
        assert app.state.ecu_seed_report.created == ["stock-hatch-20t-gdi-oem-stage"]
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/calibrations/stock-hatch-20t-gdi-oem-stage")
            ref = await client.post(
                "/api/v1/calibrations",
                json={
                    "vehicle_id": "hatch-20t-gdi",
                    "profile_id": "oem-stage",
                    "source": "reference",
                    "metadata": {"name": "Meu stage 1"},
                },
            )
    assert resp.status_code == 200 and resp.json()["metadata"]["source"] == "oem_stock"
    assert ref.status_code == 201
    assert ref.json()["content_hash"] == resp.json()["content_hash"]


async def test_lifespan_seed_failure_does_not_block(settings_factory: Any) -> None:
    app = create_app(settings_factory(db_auto_migrate=False))
    app.state.ecu_stock_sources = [
        StockCalibrationSource(
            "hatch-20t-gdi",
            "oem-stage",
            {"tables": {}, "fuel_model": {"mode": "profile_air_model"}},
        )
    ]
    async with LifespanManager(app):
        assert not hasattr(app.state, "ecu_seed_report")
