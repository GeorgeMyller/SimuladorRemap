"""Assistente de mapa base (T155; profiles RF-21, Apêndice E; G-04)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import get_catalog
from simremap.core.errors import SimRemapError
from simremap.ecu.tables import Table2D, Table3D
from simremap.profiles.contracts import BaseSetup, EcuProfileId, WizardInputs
from simremap.profiles.wizard import (
    base_ignition_deg,
    base_lambda,
    base_ve_pct,
    generate_base_map,
)

CLASSIC = "classic-20t-swap"


@pytest.fixture
def base(base_payload: Callable[..., dict[str, Any]]) -> BaseSetup:
    return BaseSetup.model_validate(base_payload())


def test_appendix_e_formulas() -> None:
    assert base_ignition_deg(4000.0, 200.0, "e100", 8.5) == pytest.approx(12.2)
    assert base_ignition_deg(500.0, 400.0, "e0", 12.0) == 5.0  # limite inferior
    assert base_ignition_deg(8000.0, 20.0, "podium", 9.0) == pytest.approx(28.0)
    assert base_lambda(60.0, 250.0, "e100") == 1.0
    assert base_lambda(85.0, 250.0, "e100") == pytest.approx(0.95)
    assert base_lambda(250.0, 250.0, "e100") == pytest.approx(0.78)
    assert base_lambda(175.0, 250.0, "podium") == pytest.approx(0.85)
    assert base_lambda(300.0, 100.0, "e27") == pytest.approx(0.82)
    assert base_ve_pct(4200.0, 100.0, 7000.0, forced=True) == pytest.approx(85.0)
    assert base_ve_pct(4200.0, 100.0, 7000.0, forced=False) == pytest.approx(90.0)
    f_rpm = 0.8 + 0.2 * (1.0 - (3700.0 / 4200.0) ** 2)
    assert base_ve_pct(500.0, 20.0, 7000.0, forced=True) == pytest.approx(85 * f_rpm * 0.64)
    assert base_ve_pct(12000.0, 100.0, 7000.0, forced=True) == pytest.approx(85 * 0.7)


def test_classic_e100_base_map(base: BaseSetup, vehicle: Callable[[str], VehicleSpec]) -> None:
    """RF-21: E100, MAP máx 250 kPa ⇒ tabelas 16×16, avanço 12,2° a 4000 rpm/200 kPa, duty."""
    wiz = WizardInputs(max_map_kpa=250.0, rev_limit_rpm=8000.0)
    result = generate_base_map(EcuProfileId.FT_PRO, base, vehicle(CLASSIC), wiz)
    content = result.content
    for table_id in ("ve", "lambda_target", "ignition_base", "inj_base_ms"):
        table = content.tables[table_id]
        assert isinstance(table, Table3D)
        assert len(table.x.values) == 16 and len(table.y.values) == 16
    ign = content.tables["ignition_base"]
    assert isinstance(ign, Table3D)
    assert ign.lookup(4000.0, 200.0) == pytest.approx(12.2, abs=0.1)
    assert ign.x.values[0] == 500.0 and ign.x.values[-1] == 8000.0
    assert ign.y.values[0] == 20.0 and ign.y.values[-1] == 270.0
    dead = content.tables["inj_dead_time"]
    assert isinstance(dead, Table2D)
    assert base.injectors is not None and dead.values == base.injectors.dead_time_ms
    assert content.fuel_model.mode == "direct_pulse_ms"
    assert 0.0 < result.estimated_peak_duty_pct <= 85.0 and result.warnings == []
    st = content.strategies
    assert st["rev_limiter"].hard_rpm == 7200.0  # type: ignore[union-attr]
    assert st["closed_loop"].enabled is True
    assert not st["two_step"].enabled and not st["antilag"].enabled
    assert not st["powershift"].enabled
    assert st["overrun"].pops_enabled is False  # type: ignore[union-attr]
    assert "boost_target" in content.tables and "cranking_fuel" in content.tables


def test_wizard_speed_density_and_default_rev(
    base: BaseSetup, vehicle: Callable[[str], VehicleSpec]
) -> None:
    result = generate_base_map(EcuProfileId.HT_ELITE, base, vehicle(CLASSIC))
    content = result.content
    assert content.fuel_model.mode == "speed_density_ve"
    assert "inj_base_ms" not in content.tables
    ve = content.tables["ve"]
    assert isinstance(ve, Table3D) and ve.x.values[-1] == 7200.0  # protection.rev_limit_rpm
    assert ve.y.values[-1] == 220.0  # max_map 200 + 20
    grid12 = generate_base_map(EcuProfileId.HT_ELITE, base, vehicle(CLASSIC), WizardInputs(grid=12))
    assert len(grid12.content.tables["ve"].x.values) == 12


def test_injector_undersized_warning(
    base_payload: Callable[..., dict[str, Any]], vehicle: Callable[[str], VehicleSpec]
) -> None:
    """EC-10: bico pequeno ⇒ duty > 85 % e aviso ``INJECTOR_UNDERSIZED``."""
    payload = base_payload()
    payload["injectors"]["flow_cc_min"] = 300.0
    small = BaseSetup.model_validate(payload)
    result = generate_base_map(
        EcuProfileId.FT_PRO, small, vehicle(CLASSIC), WizardInputs(max_map_kpa=300.0)
    )
    assert result.estimated_peak_duty_pct > 85.0
    assert result.warnings == ["INJECTOR_UNDERSIZED"]


def test_wizard_input_errors(base: BaseSetup, vehicle: Callable[[str], VehicleSpec]) -> None:
    classic = vehicle(CLASSIC)
    with pytest.raises(SimRemapError) as exc:
        generate_base_map(EcuProfileId.OEM_STAGE, base, classic)
    assert exc.value.error_code == "WIZARD_INPUT_INVALID"
    with pytest.raises(SimRemapError):
        generate_base_map(EcuProfileId.FT_PRO, BaseSetup(), classic)
    with pytest.raises(SimRemapError) as exc2:
        generate_base_map(
            EcuProfileId.FT_PRO, base, classic, WizardInputs(rev_limit_rpm=2000.0, idle_rpm=1500.0)
        )
    assert exc2.value.extra["field"] == "rev_limit_rpm"


async def test_wizard_through_api_source_wizard(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """RF-21: a calibração criada pelo PUT da base tem ``metadata.source = wizard``."""
    api.port.add(CLASSIC)
    await api.client.post(
        api.url("swap"), json={"target_profile_id": "ft-pro", "confirm_snapshot": True}
    )
    resp = await api.client.put(
        api.url("base-setup"),
        json={
            "base_version": None,
            "base_setup": base_payload(),
            "generate_base_map": True,
            "wizard": {"max_map_kpa": 250.0, "rev_limit_rpm": 7200.0},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    cal = (await api.client.get(f"/api/v1/calibrations/{data['calibration_id']}")).json()
    assert cal["metadata"]["source"] == "wizard"
    assert cal["tables"]["ignition_base"]["x"]["values"][-1] == 7200.0
    assert data["estimated_peak_duty_pct"] == pytest.approx(
        generate_base_map(
            EcuProfileId.FT_PRO,
            BaseSetup.model_validate(base_payload()),
            get_catalog().get_vehicle(CLASSIC),
            WizardInputs(max_map_kpa=250.0, rev_limit_rpm=7200.0),
        ).estimated_peak_duty_pct
    )


async def test_vehicle_aspirated_axis(
    base: BaseSetup, vehicle: Callable[[str], VehicleSpec]
) -> None:
    """Aspirado: eixo MAP até 105 kPa (sem alvo de boost)."""
    natural = vehicle("hatch-20t-gdi").model_copy(update={"induction": "natural", "turbo": None})
    payload = base.model_dump()
    result = generate_base_map(
        EcuProfileId.HT_ELITE, BaseSetup.model_validate(payload), natural, WizardInputs()
    )
    ve = result.content.tables["ve"]
    assert isinstance(ve, Table3D) and ve.y.values[-1] == 105.0
    assert "boost_target" not in result.content.tables
