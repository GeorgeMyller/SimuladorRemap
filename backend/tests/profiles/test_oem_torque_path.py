"""Caminho de torque do ``oem-stage`` (T151; profiles RF-05 a RF-09, RF-11; EC-16; Apêndice C).

A verificação do torque de freio "medido" usa o modelo de torque da própria ECU
(``torque_optimal · η(ign_opt − ign_cmd) − atrito``) sobre uma planta que segue a
pressão alvo; a confirmação no motor físico fica para o E2E com o dyno-bench.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService
from simremap.core.errors import SimRemapError
from simremap.ecu.calibration import CalibrationContent, parse_content
from simremap.ecu.compiled import compile_calibration
from simremap.ecu.service import validate_with_profile
from simremap.ecu.strategies.fuel import speed_density_air_g
from simremap.physics.contracts import SensorReadings
from simremap.profiles.adapter import ProfiledEcu, build_profiled_ecu
from simremap.profiles.hooks.oem_stage import (
    RHO_REF_KG_M3,
    OemStageHooks,
    efficiency_inverse,
)
from simremap.profiles.registry import get_registry

SensorFactory = Callable[..., SensorReadings]

RPM3 = [1000.0, 3000.0, 5000.0]
LOAD3 = [50.0, 100.0, 150.0]


def t3(  # noqa: PLR0917 - campos da tabela
    kind: str, unit: str, xs: list[float], yq: str, ys: list[float], z: Any
) -> dict[str, Any]:
    values = z if isinstance(z, list) else [[float(z)] * len(xs) for _ in ys]
    return {
        "table_id": kind,
        "kind": kind,
        "unit": unit,
        "x": {"quantity": "rpm", "values": xs},
        "y": {"quantity": yq, "values": ys},
        "values": values,
    }


def t2(kind: str, unit: str, xq: str, xs: list[float], v: Any) -> dict[str, Any]:
    values = v if isinstance(v, list) else [float(v)] * len(xs)
    return {
        "table_id": kind,
        "kind": kind,
        "unit": unit,
        "x": {"quantity": xq, "values": xs},
        "values": values,
    }


def simple_oem(
    payload: dict[str, Any],
    *,
    request: Any = 250.0,
    limit: float = 400.0,
    gear_limits: list[float] | None = None,
    friction: float = 0.0,
    pressure: float = 220.0,
    efficiency: list[float] | None = None,
    optimal: Any = None,
    params: dict[str, Any] | None = None,
) -> CalibrationContent:
    """Calibração OEM de teste do Apêndice C (tabela RF-06 em 3000 rpm)."""
    tables = payload["tables"]
    tables["torque_request"] = t3("torque_request", "N·m", RPM3, "pedal_pct", [0.0, 100.0], request)
    tables["torque_limit"] = t2("torque_limit", "N·m", "rpm", RPM3, limit)
    tables["torque_limit_gear"] = t2(
        "torque_limit_gear", "N·m", "gear", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        gear_limits or [1000.0] * 6,
    )  # fmt: skip
    tables["torque_optimal"] = t3(
        "torque_optimal", "N·m", RPM3, "load_pct", LOAD3,
        optimal if optimal is not None else [[100.0] * 3, [200.0] * 3, [300.0] * 3],
    )  # fmt: skip
    tables["ignition_optimal"] = t3("ignition_optimal", "°BTDC", RPM3, "load_pct", LOAD3, 20.0)
    tables["ignition_base"] = t3("ignition_base", "°BTDC", RPM3, "load_pct", LOAD3, 20.0)
    tables["ignition_efficiency"] = t2(
        "ignition_efficiency", "adimensional", "ign_delta_deg", [0.0, 10.0, 20.0, 45.0],
        efficiency or [1.0, 0.9, 0.7, 0.1],
    )  # fmt: skip
    tables["oem_pressure_target"] = t3(
        "oem_pressure_target", "kPa", RPM3, "load_pct", LOAD3, pressure
    )
    tables["friction_torque"] = t3("friction_torque", "N·m", RPM3, "ect_c", [0.0, 100.0], friction)
    payload["profile_params"] = {**payload["profile_params"], **(params or {})}
    return parse_content({**payload, "vehicle_id": "hatch-20t-gdi", "profile_id": "oem-stage"})


def ecu_for(
    content: CalibrationContent, vehicle: VehicleSpec, catalog: CatalogService
) -> ProfiledEcu:
    return build_profiled_ecu(
        vehicle=vehicle,
        stock_fuel=catalog.get_fuel(vehicle.stock_fuel_id),
        profile_id="oem-stage",
        ecu_state="oem",
        base_setup=None,
        calibration=content,
    )


def bound_hooks(content: CalibrationContent, v_cyl: float = 0.000496) -> OemStageHooks:
    hooks = get_registry().runtime_hooks("oem-stage", v_cyl)
    assert isinstance(hooks, OemStageHooks)
    return hooks


def test_torque_limitation_rf05(
    oem_payload: Callable[..., dict[str, Any]], sensors: SensorFactory
) -> None:
    """T_req 400, limite 350, marcha 4 a 380, atrito 30 ⇒ T_ind_des 380 e limitador torque_limit."""
    content = simple_oem(
        oem_payload(),
        request=[[0.0] * 3, [400.0] * 3],
        limit=350.0,
        gear_limits=[1000.0, 1000.0, 1000.0, 380.0, 1000.0, 1000.0],
        friction=30.0,
        optimal=[[100.0] * 3, [300.0] * 3, [500.0] * 3],
    )
    hooks = bound_hooks(content)
    compiled = compile_calibration(content, 4)
    hooks.air_charge_mg(sensors(gear=4), compiled)
    st = hooks.state
    assert st.torque_request_nm == pytest.approx(400.0)
    assert st.torque_desired_ind_nm == pytest.approx(380.0, abs=0.1)
    assert st.limiter == "torque_limit"
    hooks.air_charge_mg(sensors(gear=4, pedal_pct=0.0), compiled)
    assert hooks.state.limiter == "none"
    gear_low = simple_oem(
        oem_payload(),
        request=400.0,
        limit=390.0,
        gear_limits=[300.0] * 6,
        friction=30.0,
        optimal=[[100.0] * 3, [300.0] * 3, [500.0] * 3],
    )
    hooks2 = bound_hooks(gear_low)
    hooks2.air_charge_mg(sensors(gear=2), compile_calibration(gear_low, 4))
    assert hooks2.state.limiter == "gear"
    assert hooks2.state.torque_desired_ind_nm == pytest.approx(330.0)


def test_load_target_inversion_rf06(
    oem_payload: Callable[..., dict[str, Any]], sensors: SensorFactory
) -> None:
    """Tabela do Apêndice C: 250 N·m a 3000 rpm com η = 1 ⇒ carga alvo 125 %."""
    content = simple_oem(oem_payload(), request=250.0)
    hooks = bound_hooks(content)
    compiled = compile_calibration(content, 4)
    hooks.air_charge_mg(sensors(rpm=3000.0), compiled)
    assert hooks.state.load_target_pct == pytest.approx(125.0, abs=0.5)
    assert hooks.invert_load(3000.0, 150.0) == pytest.approx((75.0, False), abs=0.5)
    assert hooks.invert_load(500.0, 50.0) == (50.0, False)  # abaixo do mínimo: borda inferior
    assert hooks.invert_load(9000.0, 300.0)[0] == pytest.approx(150.0)


def test_inversion_saturates_at_edge_ec16(
    oem_payload: Callable[..., dict[str, Any]], sensors: SensorFactory
) -> None:
    content = simple_oem(oem_payload(), request=1400.0, limit=1400.0)
    hooks = bound_hooks(content)
    hooks.air_charge_mg(sensors(), compile_calibration(content, 4))
    assert hooks.state.load_target_pct == pytest.approx(150.0)
    assert hooks.state.limiter == "protection"


def test_torque_model_not_monotonic(oem_payload: Callable[..., dict[str, Any]]) -> None:
    """RF-06: ``torque_optimal`` não crescente ⇒ 422 ``OEM_TORQUE_MODEL_NOT_MONOTONIC``."""
    content = simple_oem(oem_payload(), optimal=[[100.0] * 3, [90.0] * 3, [300.0] * 3])
    hooks = get_registry().hooks_for("oem-stage")
    problems = hooks.validate_calibration(content, {})
    assert problems[0][0] == "OEM_TORQUE_MODEL_NOT_MONOTONIC"
    with pytest.raises(SimRemapError) as exc:
        validate_with_profile(content, hooks)
    assert exc.value.error_code == "OEM_TORQUE_MODEL_NOT_MONOTONIC"
    assert exc.value.error_status == 422
    rising = simple_oem(oem_payload(), efficiency=[0.5, 0.9, 0.7, 0.1])
    assert hooks.validate_calibration(rising, {})[0][0] == "OEM_TORQUE_MODEL_NOT_MONOTONIC"


def test_missing_torque_tables_degrade_to_speed_density(
    oem_payload: Callable[..., dict[str, Any]], sensors: SensorFactory
) -> None:
    """Sem as tabelas de torque o hook não inventa o caminho: devolve ``None`` (speed-density)."""
    payload = oem_payload()
    del payload["tables"]["torque_optimal"]
    content = parse_content({**payload, "vehicle_id": "hatch-20t-gdi", "profile_id": "oem-stage"})
    assert get_registry().hooks_for("oem-stage").validate_calibration(content, {}) == []
    hooks = bound_hooks(content)
    assert hooks.air_charge_mg(sensors(), compile_calibration(content, 4)) is None
    assert hooks.torque_path is False
    assert hooks.air_charge_mg(sensors(), object()) is None


def test_pressure_target_and_throttle_rf07(
    oem_payload: Callable[..., dict[str, Any]],
    sensors: SensorFactory,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
) -> None:
    """Pressão alvo 220 kPa ⇒ alvo de boost 220 e borboleta 100 %; 60 kPa ⇒ PI sobre o MAP."""
    hatch = vehicle("hatch-20t-gdi")
    ecu = ecu_for(simple_oem(oem_payload(), pressure=220.0), hatch, catalog)
    res = ecu.step(sensors(map_kpa=180.0), 0.001)
    assert res.status.boost_target_kpa == pytest.approx(220.0)
    assert res.commands.throttle_pct == 100.0
    assert res.profile_status.oem_pressure_target_kpa == pytest.approx(220.0)

    low = ecu_for(simple_oem(oem_payload(), pressure=80.0, request=20.0), hatch, catalog)
    first = low.step(sensors(map_kpa=95.0, pedal_pct=30.0), 0.001)
    assert first.commands.wastegate_duty_pct == 0.0
    assert first.commands.throttle_pct < 30.0  # MAP acima do alvo ⇒ fecha a borboleta
    thr = first.commands.throttle_pct
    for k in range(2, 200):
        res = low.step(sensors(map_kpa=95.0, pedal_pct=30.0, t_sim_s=1.0 + k * 0.001), 0.001)
        assert res.commands.throttle_pct <= thr + 1e-9
        thr = res.commands.throttle_pct
    for k in range(200, 1200):
        res = low.step(sensors(map_kpa=60.0, pedal_pct=30.0, t_sim_s=1.0 + k * 0.001), 0.001)
    assert res.commands.throttle_pct > thr  # MAP abaixo do alvo ⇒ abre


def test_air_charge_matches_speed_density_rf08(
    oem_content: Callable[..., CalibrationContent],
    sensors: SensorFactory,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
) -> None:
    """MAP 200 kPa e IAT 40 °C no ``hatch-20t-gdi``: ``air_charge_mg`` = speed-density (< 0,5 %)."""
    hatch = vehicle("hatch-20t-gdi")
    content = oem_content("hatch-20t-gdi", closed_loop=False)
    ecu = ecu_for(content, hatch, catalog)
    s = sensors(map_kpa=200.0, iat_c=40.0, rpm=4000.0)
    res = ecu.step(s, 0.001)
    oem = ecu.oem
    assert oem is not None
    ve = content.tables["ve"].lookup(4000.0, 200.0)  # type: ignore[call-arg]
    v_cyl = hatch.engine.displacement_cc / 4 * 1e-6
    expected = speed_density_air_g(ve, 200.0, v_cyl, 40.0, 90.0, 0.0) * 1e3
    assert oem.state.air_mg == pytest.approx(expected, rel=0.005)
    m_ref = RHO_REF_KG_M3 * v_cyl * 1e6
    assert m_ref == pytest.approx(640.9, abs=0.2)
    assert res.profile_status.oem_load_actual_pct == pytest.approx(expected / m_ref * 100.0)
    # Combustível comandado = m_ar / (λ_alvo · AFR) (sem correções nesta condição).
    lam = res.status.lambda_target
    afr = catalog.get_fuel("e27").afr_stoich
    assert res.status.fuel_mass_mg[0] == pytest.approx(expected / (lam * afr), rel=0.02)


def test_stage1_pressure_only_is_held_by_torque_limit_rf09(
    oem_payload: Callable[..., dict[str, Any]],
    sensors: SensorFactory,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
) -> None:
    """Pressão alvo +20 % com ``torque_limit`` igual: torque ≤ 105 % do limite (2500–6000 rpm)."""
    payload = oem_payload()
    pt = payload["tables"]["oem_pressure_target"]
    pt["values"] = [[min(v * 1.2, 400.0) for v in row] for row in pt["values"]]
    content = parse_content({**payload, "vehicle_id": "hatch-20t-gdi", "profile_id": "oem-stage"})
    ecu = ecu_for(content, vehicle("hatch-20t-gdi"), catalog)
    oem = ecu.oem
    assert oem is not None
    retards = []
    t = 1.0
    for rpm in range(2500, 6001, 250):
        map_kpa = 101.3
        for _ in range(30):  # planta: o MAP segue a pressão alvo do tick anterior
            t += 0.001
            res = ecu.step(sensors(rpm=float(rpm), map_kpa=map_kpa, t_sim_s=t), 0.001)
            map_kpa = min(res.profile_status.oem_pressure_target_kpa or 101.3, 300.0)
        st = oem.state
        assert st.torque_estimated_nm <= 1.05 * st.torque_limit_nm, rpm
        retards.append(res.profile_status.oem_torque_ign_retard_deg or 0.0)
        assert res.profile_status.oem_torque_limiter_active == "torque_limit"
    assert max(retards) > 0.0


def test_torque_monitoring_limp_mode_rf11(
    oem_payload: Callable[..., dict[str, Any]],
    sensors: SensorFactory,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
) -> None:
    """Torque estimado > 110 % do limite por 0,5 s ⇒ emergência: 50 % do limite e boost cortado."""
    content = simple_oem(oem_payload(), request=300.0, limit=250.0, efficiency=[1.0, 1.0, 1.0, 1.0])
    ecu = ecu_for(content, vehicle("hatch-20t-gdi"), catalog)
    events = []
    res = None
    for k in range(700):
        res = ecu.step(sensors(map_kpa=300.0, t_sim_s=1.0 + k * 0.001), 0.001)
        events.extend(res.profile_events)
    assert res is not None
    assert [e.kind for e in events].count("oem_limp_mode") == 1
    assert res.profile_status.oem_limp_mode is True
    assert res.profile_status.oem_torque_limiter_active == "limp"
    assert res.profile_status.oem_torque_desired_ind_nm == pytest.approx(125.0)
    assert res.status.arbitration_winner == "failsafe"
    assert res.commands.wastegate_duty_pct == 0.0
    # Sem monitorização a ECU não entra em emergência.
    off = simple_oem(
        oem_payload(),
        request=300.0,
        limit=250.0,
        efficiency=[1.0, 1.0, 1.0, 1.0],
        params={"torque_monitoring": False},
    )
    ecu_off = ecu_for(off, vehicle("hatch-20t-gdi"), catalog)
    for k in range(700):
        res = ecu_off.step(sensors(map_kpa=300.0, t_sim_s=1.0 + k * 0.001), 0.001)
    assert res.profile_status.oem_limp_mode is False


def test_efficiency_inverse_edges() -> None:
    xs = [0.0, 10.0, 20.0]
    vs = [1.0, 0.8, 0.8]
    assert efficiency_inverse(xs, vs, 1.2) == 0.0
    assert efficiency_inverse(xs, vs, 0.9) == pytest.approx(5.0)
    assert efficiency_inverse(xs, vs, 0.8) == 10.0
    assert efficiency_inverse(xs, vs, 0.1) == 20.0


def test_profile_status_channels_rf28(
    oem_content: Callable[..., CalibrationContent],
    sensors: SensorFactory,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
) -> None:
    ecu = ecu_for(oem_content(), vehicle("hatch-20t-gdi"), catalog)
    res = ecu.step(sensors(), 0.001)
    ps = res.profile_status
    assert ps.sync_ok and ps.ign_real_minus_cmd_deg == 0.0
    assert ps.oem_torque_request_nm is not None and ps.oem_load_target_pct is not None
    assert ps.oem_torque_limiter_active in ("none", "torque_limit", "gear", "limp", "protection")
    assert ps.t_sim_s == 1.0
    type(ps).model_validate(ps.model_dump())  # o snapshot respeita o contrato
    assert res.status.torque_request_nm is not None


class TestIdleDecelAndLowLoad:
    """Complementos do caminho de torque na integração (marcha lenta, desaceleração, piso)."""

    def test_idle_pi_requests_torque_below_idle_and_closes_above(
        self,
        oem_content: Callable[..., CalibrationContent],
        sensors: SensorFactory,
        vehicle: Callable[[str], VehicleSpec],
        catalog: CatalogService,
    ) -> None:
        ecu = ecu_for(oem_content(), vehicle("hatch-20t-gdi"), catalog)
        oem = ecu.oem
        assert oem is not None and oem.idle_rpm == 850.0
        low = ecu.step(sensors(rpm=700.0, pedal_pct=0.0, map_kpa=30.0, tps_pct=0.0), 0.001)
        assert oem.state.torque_request_nm > 0.0  # PI de marcha lenta abaixo da rotação alvo
        decel_at_idle = oem.state.decel
        assert not decel_at_idle and low.commands.throttle_pct >= 0.0
        high = ecu.step(
            sensors(t_sim_s=1.001, tick=1001, rpm=4000.0, pedal_pct=0.0, map_kpa=40.0), 0.001
        )
        assert oem.state.decel and oem.state.torque_desired_ind_nm == 0.0
        assert high.commands.throttle_pct == 0.0  # desaceleração: borboleta fechada (DFCO)

    def test_idle_rpm_from_profile_params(
        self,
        oem_content: Callable[..., CalibrationContent],
        sensors: SensorFactory,
        vehicle: Callable[[str], VehicleSpec],
        catalog: CatalogService,
    ) -> None:
        ecu = ecu_for(oem_content(idle_rpm=950.0), vehicle("hatch-20t-gdi"), catalog)
        ecu.step(sensors(rpm=900.0, pedal_pct=0.0, map_kpa=30.0), 0.001)
        assert ecu.oem is not None and ecu.oem.idle_rpm == 950.0

    def test_pressure_below_table_floor_uses_speed_density(
        self,
        oem_content: Callable[..., CalibrationContent],
        sensors: SensorFactory,
        vehicle: Callable[[str], VehicleSpec],
        catalog: CatalogService,
    ) -> None:
        """Carga parcial abaixo do piso de 80 kPa da tabela: alvo pelo speed-density."""
        ecu = ecu_for(oem_content(), vehicle("hatch-20t-gdi"), catalog)
        res = ecu.step(sensors(rpm=3000.0, pedal_pct=5.0, map_kpa=60.0, tps_pct=10.0), 0.001)
        oem = ecu.oem
        assert oem is not None
        assert 10.0 <= oem.state.pressure_target_kpa < 80.0
        assert res.profile_status.oem_pressure_target_kpa == pytest.approx(
            oem.state.pressure_target_kpa
        )

    def test_supercharger_closes_throttle_above_baro(
        self,
        oem_content: Callable[..., CalibrationContent],
        sensors: SensorFactory,
        vehicle: Callable[[str], VehicleSpec],
        catalog: CatalogService,
    ) -> None:
        """V8 com compressor: MAP 60 kPa acima do alvo ⇒ PI de borboleta acima do baro."""
        muscle = vehicle("muscle-v8-sc")
        ecu = ecu_for(oem_content("muscle-v8-sc"), muscle, catalog)
        assert ecu.oem is not None and ecu.oem.throttle_above_baro
        n = muscle.engine.n_cyl
        first = ecu.step(sensors(n_cyl=n, rpm=3000.0, pedal_pct=60.0, map_kpa=240.0), 0.001)
        target = ecu.oem.state.pressure_target_kpa
        assert target >= 101.3 - 5.0 and first.commands.throttle_pct < 100.0
        hatch = ecu_for(oem_content(), vehicle("hatch-20t-gdi"), catalog)
        assert hatch.oem is not None and not hatch.oem.throttle_above_baro
