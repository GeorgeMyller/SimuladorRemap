"""``EcuRuntime``: contrato do barramento, determinismo, status, hooks e troca de calibração.

Fontes: RF-27, RF-29, RF-30, RF-33; G-02; T310.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from simremap.ecu.arbitration import EcuRequests
from simremap.ecu.compiled import EcuHardwareConfig, compile_calibration
from simremap.ecu.contracts import EcuEvent, EcuStatus, EcuStepResult
from simremap.ecu.hooks import ALL_STRATEGIES, NullProfileHooks, ProfileHooks
from simremap.ecu.runtime import BUDGET_OVERRUN_EVENT_EVERY, EcuRuntime
from simremap.physics.contracts import ActuatorCommands

DT = 0.001


def _drive(rt: EcuRuntime, sensors: Any, n: int, n_cyl: int = 8) -> list[EcuStepResult]:
    out = []
    for i in range(n):
        rpm = 2500.0 + (i % 5000)
        knock = [0.5 if (i + k) % 97 == 0 else 0.0 for k in range(n_cyl)]
        s = sensors(
            n_cyl=n_cyl,
            t_sim_s=i * DT,
            tick=i,
            rpm=rpm,
            map_kpa=100.0 + (i % 150),
            tps_pct=float((i // 50) % 101),
            lambda_measured=0.8 + (i % 30) / 100,
            knock_intensity=knock,
            shift_request=(i // 400) % 2 == 1,
            clutch_pressed=(i // 1500) % 3 == 0,
        )
        out.append(rt.step(s, DT))
    return out


def _digest(results: list[EcuStepResult]) -> str:
    h = hashlib.sha256()
    for r in results:
        h.update(r.commands.model_dump_json().encode())
        h.update(r.status.model_dump_json().encode())
        for e in r.events:
            h.update(e.model_dump_json().encode())
    return h.hexdigest()


def test_outputs_are_valid_bus_contracts(
    full_content: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(full_content, n_cyl=8)
    for r in _drive(rt, sensors, 3000):
        ActuatorCommands.model_validate(r.commands.model_dump())
        EcuStatus.model_validate(r.status.model_dump())
        for e in r.events:
            EcuEvent.model_validate(e.model_dump())
        assert r.commands.n_cyl == r.status.n_cyl == 8


def test_g02_determinism_bit_identical(
    full_content: Any, runtime_factory: Any, sensors: Any
) -> None:
    digests = {
        _digest(_drive(runtime_factory(full_content, n_cyl=8), sensors, 2000)) for _ in range(3)
    }
    assert len(digests) == 1


def test_rf30_limiter_hit_event_with_t_sim(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt = runtime_factory(
        content_factory(strategies={"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6000.0}})
    )
    out = rt.step(sensors(t_sim_s=1.234, tick=1234, rpm=6100.0), DT)
    assert len(out.events) == 1
    assert out.events[0].kind == "limiter_hit" and out.events[0].t_sim_s == 1.234
    assert out.status.calibration_hash == rt.compiled.content_hash


def test_rf33_load_and_torque_request(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.base_tables()
    tables["torque_request"] = tb.t3(
        "torque_request",
        "torque_request",
        "N·m",
        [[0.0, 0.0], [300.0, 400.0]],
        x=[1000, 7000],
        y=[0, 100],
        yq="pedal_pct",
    )
    oem = content_factory(tables, profile_id="oem-stage")
    out = runtime_factory(oem).step(
        sensors(rpm=4000.0, pedal_pct=100.0, map_kpa=150.0, baro_kpa=100.0), DT
    )
    assert out.status.torque_request_nm == pytest.approx(350.0)
    assert out.status.load_pct == pytest.approx(150.0)
    ft = content_factory(tables, profile_id="ft-pro")
    out = runtime_factory(ft).step(
        sensors(rpm=4000.0, pedal_pct=100.0, map_kpa=400.0, baro_kpa=100.0), DT
    )
    assert out.status.torque_request_nm is None
    assert 0.0 <= out.status.load_pct <= 300.0


def test_rf31_cam_targets(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    tables = tb.full_tables(4)
    out = runtime_factory(content_factory(tables)).step(sensors(), DT)
    assert out.commands.vvt_intake_target_deg == 20.0
    assert out.commands.vvt_exhaust_target_deg == -10.0
    out = runtime_factory(content_factory()).step(sensors(), DT)
    assert out.commands.vvt_intake_target_deg == 0.0 and out.commands.vvt_exhaust_target_deg == 0.0


def test_throttle_and_bypass(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = runtime_factory(content_factory())
    out = rt.step(sensors(pedal_pct=37.0), DT)
    assert out.commands.throttle_pct == 37.0 and not out.commands.bypass_open
    out = rt.step(sensors(t_sim_s=DT, tick=1, tps_pct=0.0, map_kpa=160.0), DT)
    assert out.commands.bypass_open


class RecordingHooks(NullProfileHooks):
    def __init__(self, supported: frozenset[str] = ALL_STRATEGIES) -> None:
        super().__init__("ft-pro")
        self.supported = supported
        self.adjust_calls = 0

    def supported_strategies(self) -> frozenset[str]:
        return self.supported

    def adjust_requests(self, sensors: object, requests: object) -> None:
        assert isinstance(requests, EcuRequests)
        self.adjust_calls += 1
        requests.failsafe.active = True
        requests.failsafe.boost_ceiling_kpa = 150.0  # ex.: teto de torque do OEM


def test_rf29_hooks_adjust_requests_and_supported(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    hooks = RecordingHooks(frozenset({"boost_control"}))
    assert isinstance(hooks, ProfileHooks)
    content = content_factory(
        tb.full_tables(4),
        {
            "boost_control": {"kind": "boost_control"},
            "rev_limiter": {"kind": "rev_limiter", "hard_rpm": 3000.0},
        },
    )
    rt = runtime_factory(content, hooks=hooks)
    out = rt.step(sensors(rpm=3500.0, tps_pct=100.0), DT)
    assert hooks.adjust_calls == 1
    assert out.status.boost_target_kpa == 150.0
    assert out.commands.fuel_cut == [False] * 4  # rev_limiter não suportado pelo perfil
    assert out.status.arbitration_winner == "failsafe"


def test_enabled_strategies_flag(content_factory: Any, runtime_factory: Any, sensors: Any) -> None:
    content = content_factory(
        strategies={"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 3000.0}}
    )
    rt = runtime_factory(content, enabled_strategies=frozenset({"closed_loop"}))
    assert rt.step(sensors(rpm=3500.0), DT).commands.fuel_cut == [False] * 4
    rt = runtime_factory(content, enabled_strategies=None)
    assert rt.step(sensors(rpm=3500.0), DT).commands.fuel_cut == [True] * 4


def test_rf27_swap_at_tick_boundary_without_mixing(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    old = content_factory()
    tables = tb.base_tables()
    tables["ignition_base"] = tb.t3("ignition_base", "ignition_base", "°BTDC", 30.0)
    tables["ve"] = tb.t3("ve", "ve", "%", 80.0)
    new = content_factory(tables)
    rt: EcuRuntime = runtime_factory(old)
    first = rt.step(sensors(), DT)
    rt.swap_calibration(compile_calibration(new, 4, calibration_id="cal-test", version=2), "full")
    pending_before = rt.swap_pending
    second = rt.step(sensors(t_sim_s=DT, tick=1), DT)
    assert pending_before and not rt.swap_pending
    assert rt.applied_t_sim_s == DT
    assert first.status.calibration_hash != second.status.calibration_hash
    # Tudo no tick seguinte já é da versão nova (sem mistura).
    assert second.commands.ignition_advance_deg == [30.0] * 4
    assert second.status.fuel_mass_mg[0] / first.status.fuel_mass_mg[0] == pytest.approx(80 / 90)


def test_live_swap_keeps_integrators_and_knock(
    content_factory: Any, runtime_factory: Any, sensors: Any, tb: Any
) -> None:
    strategies = {
        "closed_loop": {"kind": "closed_loop", "delay_after_start_s": 0.0},
        "knock_control": {"kind": "knock_control"},
    }
    rt: EcuRuntime = runtime_factory(content_factory(tb.base_tables(), strategies))
    for i in range(200):
        rt.step(
            sensors(t_sim_s=i * DT, tick=i, lambda_measured=0.9, knock_intensity=[0.9, 0, 0, 0]), DT
        )
    integ, retard = rt.closed_loop.integ, list(rt.knock.retard)
    tables = tb.base_tables()
    tables["ve"] = tb.t3("ve", "ve", "%", 95.0)
    rt.swap_calibration(compile_calibration(content_factory(tables, strategies), 4), "live_tables")
    rt.step(sensors(t_sim_s=0.2, tick=200, lambda_measured=0.85), DT)
    assert rt.closed_loop.integ == pytest.approx(integ, abs=1e-3)
    assert rt.knock.retard[0] == pytest.approx(retard[0], abs=1e-2)
    with pytest.raises(ValueError, match="estratégias"):
        rt.swap_calibration(compile_calibration(content_factory(tables), 4), "live_tables")
    with pytest.raises(ValueError, match="n_cyl"):
        rt.swap_calibration(compile_calibration(content_factory(tables, strategies), 6), "full")


def test_full_swap_rebuilds_strategies(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt: EcuRuntime = runtime_factory(content_factory())
    assert rt.step(sensors(rpm=6500.0), DT).commands.fuel_cut == [False] * 4
    limited = content_factory(
        strategies={"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6000.0}}
    )
    rt.swap_calibration(compile_calibration(limited, 4))
    assert rt.step(sensors(t_sim_s=DT, tick=1, rpm=6500.0), DT).commands.fuel_cut == [True] * 4


def test_ec12_budget_overrun_event(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt: EcuRuntime = runtime_factory(content_factory())
    for _ in range(BUDGET_OVERRUN_EVENT_EVERY - 1):
        rt.record_step_duration(0.0006)
    rt.record_step_duration(0.0001)
    assert not [e for e in rt.step(sensors(), DT).events if e.kind == "budget_overrun"]
    rt.record_step_duration(0.001)
    out = rt.step(sensors(t_sim_s=DT, tick=1), DT)
    assert [e.value for e in out.events if e.kind == "budget_overrun"] == [1000.0]


def test_constructor_validation(content_factory: Any, tb: Any) -> None:
    compiled = compile_calibration(content_factory(), 4)
    with pytest.raises(ValueError, match="EcuHardwareConfig"):
        EcuRuntime(compiled, None, None)
    with pytest.raises(ValueError, match="n_cyl"):
        EcuRuntime(compiled, None, tb.hardware(6))
    with pytest.raises(ValueError):
        compile_calibration(content_factory(), 9)


def test_hardware_config_validation_and_catalog_builder() -> None:
    with pytest.raises(ValueError):
        EcuHardwareConfig(
            n_cyl=0,
            displacement_cc=2000,
            injector_flow_cc_min=500,
            afr_stoich=14.7,
            fuel_density_g_cc=0.74,
        )
    with pytest.raises(ValueError):
        EcuHardwareConfig(
            n_cyl=4,
            displacement_cc=-1,
            injector_flow_cc_min=500,
            afr_stoich=14.7,
            fuel_density_g_cc=0.74,
        )
    with pytest.raises(ValueError):
        EcuHardwareConfig(
            n_cyl=4,
            displacement_cc=2000,
            injector_flow_cc_min=500,
            afr_stoich=0,
            fuel_density_g_cc=0.74,
        )
    with pytest.raises(ValueError):
        EcuHardwareConfig(
            n_cyl=4,
            displacement_cc=2000,
            injector_flow_cc_min=500,
            afr_stoich=14.7,
            fuel_density_g_cc=0.74,
            dead_time_v=(8.0,),
            dead_time_ms=(1.0,),
        )
    with pytest.raises(ValueError):
        EcuHardwareConfig(
            n_cyl=4,
            displacement_cc=2000,
            injector_flow_cc_min=500,
            afr_stoich=14.7,
            fuel_density_g_cc=0.74,
            dead_time_v=(10.0, 8.0),
            dead_time_ms=(1.0, 1.0),
        )

    class Grid:
        x_values = (8.0, 16.0)
        y_values = (100.0, 300.0, 500.0)
        z_values = ((2.0, 1.0), (1.5, 0.5), (1.0, 0.2))

    class Inj:
        dead_time_ms = Grid()
        dp_ref_kpa = 300.0
        flow_cc_min = 450.0
        count_per_cyl = 1

    class Engine:
        n_cyl = 4
        displacement_cc = 1998.0

    class Vehicle:
        injectors = Inj()
        engine = Engine()

    class Fuel:
        afr_stoich = 13.2
        density_kg_m3 = 745.0

    hw = EcuHardwareConfig.from_vehicle(Vehicle(), Fuel())  # type: ignore[arg-type]
    assert hw.dead_time_ms == (1.5, 0.5)
    assert hw.dead_time(12.0) == pytest.approx(1.0)
    assert hw.fuel_density_g_cc == pytest.approx(0.745)


def test_reset_session_and_events_list_is_per_tick(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    rt: EcuRuntime = runtime_factory(
        content_factory(strategies={"rev_limiter": {"kind": "rev_limiter", "hard_rpm": 6000.0}})
    )
    a = rt.step(sensors(rpm=6100.0), DT)
    b = rt.step(sensors(t_sim_s=DT, tick=1, rpm=6100.0), DT)
    assert len(a.events) == 1 and b.events == []
    rt.reset_session()
    assert rt.closed_loop.stft == 0.0
    json.dumps([e.model_dump(mode="json") for e in a.events])


def test_bov_opens_on_closed_throttle_with_pressure_before_it(
    content_factory: Any, runtime_factory: Any, sensors: Any
) -> None:
    """B4 (003 T032): borboleta fechada no coastdown ⇒ MAP 8–20 kPa e o turbo ainda com
    pressão antes da borboleta: a BOV (referenciada ao coletor, como uma diverter real) abre
    pela diferença pré-borboleta − MAP, não por MAP > baro + 10 (que nunca acontecia)."""
    rt = runtime_factory(content_factory())
    coast = rt.step(sensors(tps_pct=0.0, map_kpa=15.0, boost_pre_throttle_kpa=180.0), DT)
    assert coast.commands.bypass_open
    open_throttle = rt.step(
        sensors(t_sim_s=DT, tick=1, tps_pct=60.0, map_kpa=150.0, boost_pre_throttle_kpa=180.0),
        DT,
    )
    assert not open_throttle.commands.bypass_open
    balanced = rt.step(
        sensors(t_sim_s=2 * DT, tick=2, tps_pct=0.0, map_kpa=95.0, boost_pre_throttle_kpa=100.0),
        DT,
    )
    assert not balanced.commands.bypass_open
