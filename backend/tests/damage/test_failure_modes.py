"""Os 6 modos de falha: 1 cenário determinístico e 1 falha catastrófica cada, com bloqueio no
mesmo tick (T134; RF-18, RF-19, RF-29; EC-05, EC-06)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from kfm_helpers import SPEC_CONFIG, Driver, ModelFactory, make_event, make_state, spec_config

from simremap.damage.contracts import DamageState, FailureMechanism, FailureMode
from simremap.damage.errors import DamageError
from simremap.damage.model import DamageModel

THR = SPEC_CONFIG.preignition_threshold_for("e27")


@dataclass
class FakePhysics:
    locks: list[str] = field(default_factory=list)

    def lock(self, reason: str) -> None:
        self.locks.append(reason)


@dataclass(frozen=True)
class Scenario:
    rpm: float
    mode: FailureMode
    mechanism: FailureMechanism
    component: str
    events: Callable[[int, float, float], Any] = make_event
    overrides: dict[str, Any] = field(default_factory=dict)
    seconds: float = 30.0


SCENARIOS = {
    "knock_damage": Scenario(
        6000.0,
        FailureMode.KNOCK_DAMAGE,
        FailureMechanism.HEAD_GASKET_BREACH,
        "head_gasket",
        events=lambda c, t, r: make_event(c, t, r, p_max_kpa=24_000.0),
    ),
    "pre_ignition": Scenario(
        5000.0,
        FailureMode.PRE_IGNITION,
        FailureMechanism.HOT_SPOT_PREIGNITION,
        "piston:2",
        events=lambda c, t, r: make_event(c, t, r, p_max_kpa=10_000.0, imep_kpa=1000.0),
        overrides={"hot_spot_temp_c": [500.0, THR + 100.0, 500.0, 500.0]},
    ),
    "egt_overtemp": Scenario(
        3500.0,
        FailureMode.EGT_OVERTEMP,
        FailureMechanism.EXHAUST_VALVE_BURN,
        "valves:4",
        overrides={"egt_c": [850.0, 850.0, 850.0, 1100.0]},
    ),
    "rod_failure": Scenario(
        5000.0,
        FailureMode.ROD_FAILURE,
        FailureMechanism.ROD_OVERLOAD,
        "rod:",
        overrides={"torque_nm": 440.0},
    ),
    "piston_failure": Scenario(
        6000.0,
        FailureMode.PISTON_FAILURE,
        FailureMechanism.KNOCK_EROSION,
        "piston:3",
        events=lambda c, t, r: make_event(c, t, r, knock=c == 3, theta_onset=10.0),
    ),
    "turbo_meltdown": Scenario(
        3500.0,
        FailureMode.TURBO_MELTDOWN,
        FailureMechanism.TURBINE_CREEP,
        "turbo:turbine",
        overrides={"egt_collector_c": 1010.0},
    ),
}


def _run(model: DamageModel, scenario: Scenario) -> tuple[list[DamageState], Driver]:
    driver = Driver(
        model,
        scenario.rpm,
        event_factory=scenario.events,
        state_overrides=lambda _t: scenario.overrides,
        keep_states=True,
    )
    driver.advance(scenario.seconds, until_locked=True)
    return driver.states, driver


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_failure_mode_scenario(name: str, make_model: ModelFactory) -> None:
    scenario = SCENARIOS[name]
    physics = FakePhysics()
    model = make_model(physics=physics)
    states, driver = _run(model, scenario)
    final = states[-1]
    catastrophic = [f for f in model.failures if f.catastrophic]
    assert len(catastrophic) == 1
    failure = catastrophic[0]
    assert failure.mode == scenario.mode
    assert failure.mechanism == scenario.mechanism
    assert failure.component_id.startswith(scenario.component)
    assert failure.health_after == 0.0 and not failure.simulated_only
    # RF-19: bloqueio e lock da física no mesmo tick da falha
    assert final.engine_locked and failure in final.new_failures
    assert final.tick == failure.tick
    assert physics.locks == [scenario.mode.value]
    # avisos de saúde ≤ 0,50: no máximo 1 por componente
    warnings = [f for f in model.failures if not f.catastrophic]
    assert len({w.component_id for w in warnings}) == len(warnings)
    assert all(w.health_after <= 0.5 for w in warnings)
    # determinismo: mesma seed ⇒ mesma falha
    again = make_model()
    _run(again, scenario)
    other = next(f for f in again.failures if f.catastrophic)
    assert (other.tick, other.component_id, other.failure_event_id) == (
        failure.tick,
        failure.component_id,
        failure.failure_event_id,
    )
    # EC-05: motor bloqueado ⇒ estado congelado, sem sorteios nem eventos
    digest = model.damage_digest()
    frozen = list(driver.run(0.05))
    assert all(s.engine_locked and s.new_failures == [] for s in frozen)
    assert frozen[-1].components == final.components
    assert model.damage_digest() != digest  # só tick/t avançam
    assert len(model.failures) == len(again.failures)


def test_warning_event_is_emitted_once(make_model: ModelFactory) -> None:
    model = make_model()
    driver = Driver(model, 6000.0, event_factory=lambda c, t, r: make_event(c, t, r, knock=c == 3))
    driver.advance(3.0)
    warnings = [f for f in model.failures if not f.catastrophic]
    assert len(warnings) == 1
    assert (warnings[0].mode, warnings[0].mechanism) == (
        FailureMode.KNOCK_DAMAGE,
        FailureMechanism.RING_LAND_CRACK,
    )
    assert warnings[0].component_id == "piston:3"
    assert "knock_intensity" in warnings[0].causal_variables


def test_two_failures_in_same_tick_lock_once(make_model: ModelFactory) -> None:
    physics = FakePhysics()
    model = make_model(sim_hz=100, physics=physics)
    driver = Driver(model, 6000.0, sim_hz=100, state_overrides=lambda _t: {"torque_nm": 560.0})
    state = driver.advance(1.0, until_locked=True)
    assert state is not None
    ids = [f.component_id for f in state.new_failures]
    assert len(ids) >= 2
    assert ids == sorted(ids, key=model.component_ids.index)
    assert physics.locks == ["rod_failure"]


def test_restore_unlocks_and_resets(make_model: ModelFactory) -> None:
    model = make_model()
    model.step(make_state(1, 0.001, 0.0, turbo_rpm=240_000.0), 0.001)
    locked_before_restore = model.engine_locked
    assert locked_before_restore
    weights = model.rod_weights
    model.restore()
    assert not model.engine_locked and model.restore_count == 1
    assert model.intact and model.rod_weights == weights
    state = model.step(make_state(2, 0.002, 0.0), 0.001)
    assert not state.engine_locked
    assert all(c.health == 1.0 and not c.failed and not c.damage_by_cause for c in state.components)
    health = model.engine_health()
    assert health.intact and health.restore_count == 1 and health.integrity_pct == 100.0


def test_damage_off_accumulates_virtual_health_only(make_model: ModelFactory) -> None:
    physics = FakePhysics()
    model = make_model(damage_enabled=False, physics=physics)
    driver = Driver(model, 6000.0, event_factory=lambda c, t, r: make_event(c, t, r, knock=c == 3))
    state = driver.advance(8.0)
    assert state is not None and not state.engine_locked and not state.damage_enabled
    piston = next(c for c in state.components if c.component_id == "piston:3")
    assert piston.health == 1.0 and piston.virtual_health == 0.0 and not piston.failed
    virtual = [f for f in model.failures if f.health_after == 0.0]
    assert len(virtual) == 1
    assert virtual[0].simulated_only and not virtual[0].catastrophic
    assert physics.locks == []
    assert all(e.simulated_only for e in model.knock_events) or model.knock_events == []


def test_damage_off_requires_feature() -> None:
    from kfm_helpers import build_e27, build_hatch

    cfg = spec_config(features=("knock", "signal"))
    with pytest.raises(DamageError) as info:
        DamageModel(cfg, build_hatch(), build_e27(), 1, damage_enabled=False)
    assert info.value.error_code == "DAMAGE_CONFIG_INVALID"


def test_step_validations(make_model: ModelFactory) -> None:
    model = make_model()
    with pytest.raises(DamageError) as info:
        model.step(make_state(1, 0.001, 0.0), 0.002)
    assert info.value.error_code == "DAMAGE_DT_MISMATCH"
    with pytest.raises(DamageError, match="cilindros"):
        model.step(make_state(1, 0.001, 0.0, n_cyl=6), 0.001)
    bad = make_event(1, 0.0005, 3000.0).model_copy(update={"burned_fraction": [0.5]})
    with pytest.raises(DamageError) as info:
        model.step(make_state(1, 0.001, 3000.0, events=[bad]), 0.001)
    assert info.value.error_code == "DAMAGE_INPUT_INVALID"


def test_fuel_change_only_with_engine_stopped(make_model: ModelFactory) -> None:
    from kfm_helpers import build_e27

    model = make_model()
    model.step(make_state(1, 0.001, 3000.0), 0.001)
    with pytest.raises(DamageError) as info:
        model.set_fuel(build_e27())
    assert info.value.error_code == "DAMAGE_FUEL_CHANGE_WHILE_RUNNING"
    model.step(make_state(2, 0.002, 0.0), 0.001)
    model.set_fuel(build_e27(fuel_id="podium", ron=102.0, mon=88.0))
    assert model.hot_spot_threshold_c == SPEC_CONFIG.preignition_threshold_for("podium")
