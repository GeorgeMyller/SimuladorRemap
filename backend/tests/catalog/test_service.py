"""RF-11, RF-19, RF-21, RF-23: ``CatalogService`` e a instância única."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog import service as service_module
from simremap.catalog.errors import (
    CatalogInvalid,
    FuelNotAllowed,
    FuelNotFound,
    ReferenceCurveNotFound,
    VehicleIdInvalid,
    VehicleNotFound,
    VehicleNotValidated,
)
from simremap.catalog.loader import Catalog
from simremap.catalog.service import (
    CatalogService,
    get_catalog,
    load_catalog,
    set_catalog,
    startup_catalog,
)
from simremap.core.config import Settings
from simremap.core.errors import SimRemapError


def _validate_hatch(copy: Any) -> None:
    """Cenário do fim do Sprint 1: só o hatch validado, os outros 3 em draft."""
    for vid in ("coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"):
        copy.edit(
            f"vehicles/{vid}/vehicle.json",
            lambda d: d.update(validation_status="draft", validated_on=None),
            rehash_after=False,
        )
    copy.edit(
        "vehicles/hatch-20t-gdi/vehicle.json",
        lambda d: d.update(
            validation_status="validated", validated_on="2026-10-25", data_version=2
        ),
    )


def _draft(copy: Any, vid: str) -> Catalog:
    copy.edit(
        f"vehicles/{vid}/vehicle.json",
        lambda d: d.update(validation_status="draft", validated_on=None),
    )
    catalog: Catalog = copy.load()
    return catalog


class TestVehicles:
    def test_list_defaults_to_validated(self, service: CatalogService) -> None:
        # T406: os 4 veículos validados pela física aparecem sem include_drafts
        items = service.list_vehicles()
        assert [i.vehicle_id for i in items] == list(service.vehicle_ids)
        assert all(i.validation_status == "validated" for i in items)
        assert service.list_vehicles(include_drafts=True) == items
        hatch = items[0]
        assert hatch.n_cyl == 4
        assert hatch.displacement_cc == 1984.0
        assert hatch.rated.peak_power_whp == 220.0

    def test_list_with_validated(self, catalog_copy: Any) -> None:
        _validate_hatch(catalog_copy)
        svc = CatalogService(catalog_copy.load())
        assert [v.vehicle_id for v in svc.list_vehicles()] == ["hatch-20t-gdi"]
        assert len(svc.list_vehicles(include_drafts=True)) == 4

    def test_get_vehicle_errors(self, service: CatalogService) -> None:
        assert service.get_vehicle("hatch-20t-gdi").engine.compression_ratio == 9.6
        with pytest.raises(VehicleNotFound):
            service.get_vehicle("abc-def")
        for bad in ("../etc", "ABC-DEF", "semhifen", "a-" + "b" * 60):
            with pytest.raises(VehicleIdInvalid):
                service.get_vehicle(bad)

    def test_detail(self, service: CatalogService) -> None:
        detail = service.get_vehicle_detail("hatch-20t-gdi")
        assert detail.catalog_version == "1.1.0"
        assert detail.data_sha256 == service.data_sha256("hatch-20t-gdi")
        assert [f.fuel_id for f in detail.fuels] == ["e27", "podium", "e0"]
        assert detail.estimated_fields == service.estimated_fields("hatch-20t-gdi")
        assert service.get_vehicle_detail("hatch-20t-gdi") is detail  # cache

    def test_limits_rf28(self, service: CatalogService) -> None:
        lim = service.get_vehicle("hatch-20t-gdi").mechanical_limits
        assert (lim.max_rod_load_kn, lim.max_cylinder_pressure_bar) == (52.0, 120.0)
        assert (lim.max_piston_temp_c, lim.valve_float_rpm) == (330.0, 7200.0)
        assert lim.egt_limit_c == lim.egt_max_c == 950.0


class TestSession:
    def test_draft_refused(self, catalog_copy: Any) -> None:
        service = CatalogService(_draft(catalog_copy, "muscle-v8-sc"), allow_drafts=False)
        assert service.get_for_session("hatch-20t-gdi").validation_status == "validated"
        with pytest.raises(VehicleNotValidated) as exc:
            service.get_for_session("muscle-v8-sc")
        assert exc.value.error_status == 409
        assert "Sprint 4" in exc.value.detail

    def test_draft_allowed_logs(
        self,
        catalog_copy: Any,
        caplog: pytest.LogCaptureFixture,
        log_events: Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]],
    ) -> None:
        svc = CatalogService(_draft(catalog_copy, "muscle-v8-sc"), allow_drafts=True)
        with caplog.at_level(logging.INFO, logger="simremap.catalog"):
            spec = svc.get_for_session("muscle-v8-sc")
        assert spec.vehicle_id == "muscle-v8-sc"
        events = [e for e in log_events(caplog) if e.get("event") == "catalog.draft_used"]
        assert events and events[0]["vehicle_id"] == "muscle-v8-sc"

    def test_validated_vehicle(self, catalog_copy: Any) -> None:
        _validate_hatch(catalog_copy)
        svc = CatalogService(catalog_copy.load(), allow_drafts=False)
        assert svc.get_for_session("hatch-20t-gdi").validation_status == "validated"

    def test_stock_calibration(self, service: CatalogService) -> None:
        assert service.stock_calibration_id("hatch-20t-gdi") == "stock-hatch-20t-gdi-oem-stage"
        payload = service.get_factory_calibration_payload("hatch-20t-gdi", "oem-stage")
        assert payload["metadata"]["source"] == "oem_stock"
        payload["metadata"]["source"] = "user"  # cópia: não altera o catálogo
        again = service.get_factory_calibration_payload("hatch-20t-gdi", "oem-stage")
        assert again["metadata"]["source"] == "oem_stock"
        assert set(service.factory_calibrations("classic-20t-swap")) == {"oem-stage", "ft-pro"}
        with pytest.raises(SimRemapError) as exc:
            service.get_factory_calibration_payload("hatch-20t-gdi", "ft-pro")
        assert exc.value.error_code == "RESOURCE_NOT_FOUND"

    def test_schedule_rf21(self, service: CatalogService) -> None:
        schedule = service.get_reference_command_schedule("hatch-20t-gdi")
        rpms = [p.rpm for p in schedule.points]
        assert rpms[0] == 2000.0 and rpms[-1] == 6500.0 and len(rpms) == 19
        assert all(p.throttle_pct == 100.0 for p in schedule.points)
        # MAP alvo afinado contra a física (T267, gain-calibration), teto 235 kPa da série:
        # pico de 221,8 kPa a 5000 rpm e queda até 198,2 kPa a 6500 rpm (proteção do turbo)
        assert max(p.map_target_kpa for p in schedule.points) == 221.8
        assert schedule.points[-1].map_target_kpa == 198.2
        # 2000–3500 rpm limitados por detonação/pressão de pico (12,6–18,4°; integração)
        assert all(12.0 <= p.ignition_advance_deg <= 35.0 for p in schedule.points)
        assert schedule.points[0].ignition_advance_deg == 12.6
        assert schedule.fuel_id == "e27"


class TestFuels:
    def test_fuels_rf11(self, service: CatalogService) -> None:
        assert service.get_fuel("e27").afr_stoich == 13.2
        assert service.get_fuel("e100").density_kg_m3 == 789.0
        assert service.get_fuel("e100").density_g_cc == pytest.approx(0.789)
        assert service.get_fuel("podium").afr_stoich == 14.4
        assert service.get_fuel("e0").afr_stoich == 14.7
        with pytest.raises(FuelNotFound):
            service.get_fuel("e85")

    def test_fuel_not_allowed(self, service: CatalogService) -> None:
        assert [f.fuel_id for f in service.allowed_fuels("muscle-v8-sc")] == ["e27", "podium", "e0"]
        assert service.get_fuel_for_vehicle("classic-20t-swap", "e100").fuel_id == "e100"
        with pytest.raises(FuelNotAllowed) as exc:
            service.get_fuel_for_vehicle("muscle-v8-sc", "e100")
        assert exc.value.extra["allowed_fuel_ids"] == ["e27", "podium", "e0"]
        assert exc.value.error_status == 409


class TestCurves:
    def test_filters(self, service: CatalogService) -> None:
        curves = service.get_reference_curves("hatch-20t-gdi")
        assert [c.curve_id for c in curves] == ["stock-e27"]
        assert service.get_reference_curves("hatch-20t-gdi", fuel_id="e27") == curves
        with pytest.raises(ReferenceCurveNotFound):
            service.get_reference_curves("hatch-20t-gdi", fuel_id="e100")
        with pytest.raises(ReferenceCurveNotFound):
            service.get_reference_curves("hatch-20t-gdi", calibration_ref="stage-1")
        assert len(service.all_reference_curves()) == 4

    def test_response(self, service: CatalogService) -> None:
        resp = service.reference_curve_response("coupe-30t-i6")
        assert resp.benchmark_sha256 == service.benchmark_sha256
        assert resp.catalog_sha256 == service.catalog_sha256


class TestSingleton:
    def test_lazy_get_catalog(self) -> None:
        first = get_catalog()
        assert get_catalog() is first
        assert first.allow_drafts is False  # SIMREMAP_ENV ausente = prod

    def test_set_and_load(self, catalog_copy: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIMREMAP_CATALOG_DIR", str(catalog_copy.root))
        monkeypatch.setenv("SIMREMAP_CATALOG_ALLOW_DRAFTS", "true")
        svc = load_catalog()
        assert svc.catalog.root == catalog_copy.root
        assert svc.allow_drafts is True
        assert get_catalog() is svc
        set_catalog(None)
        assert service_module._SERVICE is None

    def test_env_controls_drafts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SIMREMAP_CATALOG_ALLOW_DRAFTS", raising=False)
        assert load_catalog(env="dev").allow_drafts is True
        assert load_catalog(env="prod").allow_drafts is False
        assert load_catalog(env="prod", allow_drafts=True).allow_drafts is True

    def test_startup_ok(
        self,
        settings: Settings,
        caplog: pytest.LogCaptureFixture,
        log_events: Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]],
    ) -> None:
        with caplog.at_level(logging.INFO, logger="simremap.catalog"):
            svc = startup_catalog(settings)
        assert svc.allow_drafts is True  # env = test
        event = next(e for e in log_events(caplog) if e.get("event") == "startup.catalog")
        assert event["vehicles"] == 4
        assert event["validated"] == 4  # T406
        assert event["catalog_sha256"] == svc.catalog_sha256

    def test_startup_failure_exit_4(
        self,
        catalog_copy: Any,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        log_events: Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]],
    ) -> None:
        catalog_copy.edit("vehicles/hatch-20t-gdi/vehicle.json", lambda d: d.pop("engine"))
        monkeypatch.setenv("SIMREMAP_CATALOG_DIR", str(catalog_copy.root))
        with (
            caplog.at_level(logging.INFO, logger="simremap.catalog"),
            pytest.raises(CatalogInvalid) as exc,
        ):
            startup_catalog()
        assert exc.value.exit_code == 4
        event = next(e for e in log_events(caplog) if e.get("event") == "startup.failed")
        assert event["code"] == "CATALOG_INVALID"
        assert event["issues"][0]["pointer"] == "/engine"
        assert event["issues"][0]["file"] == "vehicles/hatch-20t-gdi/vehicle.json"
