"""Dano mecânico: biela, sobre-rotação de válvulas, turbina e junta (T133; RF-14 a RF-17; D-21)."""

from __future__ import annotations

import pytest
from kfm_helpers import SPEC_CONFIG, Driver, ModelFactory, build_hatch, make_event, make_state

from simremap.catalog.contracts import VehicleSpec
from simremap.damage.contracts import FailureMechanism, FailureMode
from simremap.damage.errors import DamageError
from simremap.damage.mechanical import (
    StructuralLimits,
    bearing_overrev_rate,
    peak_pressure_damage,
    rod_damage,
    rod_load_ratio,
    turbo_overspeed,
    valve_overrev,
)

CFG = SPEC_CONFIG
LIMITS = StructuralLimits.from_vehicle(build_hatch())


class TestLimits:
    def test_catalog_limits_converted_to_n_and_kpa(self) -> None:
        assert LIMITS.rod_force_limit_n == 52_000.0
        assert LIMITS.cylinder_pressure_limit_kpa == 12_000.0
        assert LIMITS.rod_torque_limit_nm == 420.0
        assert LIMITS.egt_limit_c == 950.0
        assert LIMITS.turbo_max_rpm == 210_000.0

    def test_missing_limit_is_config_invalid(self, hatch_vehicle: VehicleSpec) -> None:
        limits = hatch_vehicle.mechanical_limits.model_copy(update={"turbo_max_rpm": None})
        broken = hatch_vehicle.model_copy(update={"mechanical_limits": limits})
        with pytest.raises(DamageError) as info:
            StructuralLimits.from_vehicle(broken)
        assert info.value.error_code == "DAMAGE_CONFIG_INVALID"
        assert info.value.extra["field"] == "mechanical_limits.turbo_max_rpm"
        no_rod = hatch_vehicle.mechanical_limits.model_copy(update={"rod_torque_limit_nm": None})
        with pytest.raises(DamageError, match="rod_torque_limit_nm"):
            StructuralLimits.from_vehicle(
                hatch_vehicle.model_copy(update={"mechanical_limits": no_rod})
            )


class TestRod:
    def test_ratio_uses_torque_or_force(self) -> None:
        assert rod_load_ratio(430.0, 30_000.0, LIMITS) == pytest.approx(430 / 420)
        assert rod_load_ratio(300.0, 57_200.0, LIMITS) == pytest.approx(1.1)

    def test_damage_law(self) -> None:
        assert rod_damage(0.99, 1.0, CFG) == (0.0, False)
        damage, instant = rod_damage(1.1, 1.05, CFG)
        assert damage == pytest.approx(0.002 * 3.0 * 1.05) and not instant
        assert rod_damage(1.30, 1.0, CFG)[1] is True

    def test_410_nm_for_60_s_keeps_rods_intact(self, make_model: ModelFactory) -> None:
        model = make_model(sim_hz=100)
        driver = Driver(model, 5000.0, sim_hz=100, state_overrides=lambda _t: {"torque_nm": 410.0})
        state = driver.advance(60.0)
        assert state is not None
        assert all(c.health == 1.0 for c in state.components if c.kind in ("rod", "bearings"))

    def test_430_nm_breaks_heaviest_rod(self, make_model: ModelFactory) -> None:
        model = make_model(seed=42)
        weights = model.rod_weights
        assert all(0.9 <= w <= 1.1 for w in weights)
        driver = Driver(model, 5000.0, state_overrides=lambda _t: {"torque_nm": 430.0})
        driver.advance(15.0, until_locked=True)
        failure = next(f for f in model.failures if f.catastrophic)
        heaviest = weights.index(max(weights)) + 1
        assert failure.component_id == f"rod:{heaviest}"
        assert (failure.mode, failure.mechanism) == (
            FailureMode.ROD_FAILURE,
            FailureMechanism.ROD_OVERLOAD,
        )
        assert failure.t_sim_s == pytest.approx(8.13 / max(weights), rel=0.02)
        again = make_model(seed=42)
        Driver(again, 5000.0, state_overrides=lambda _t: {"torque_nm": 430.0}).advance(
            15.0, until_locked=True
        )
        assert (
            next(f for f in again.failures if f.catastrophic).component_id == failure.component_id
        )

    def test_550_nm_breaks_on_first_cycle(self, make_model: ModelFactory) -> None:
        model = make_model()
        driver = Driver(model, 5000.0, state_overrides=lambda _t: {"torque_nm": 550.0})
        state = driver.advance(1.0, until_locked=True)
        assert state is not None and state.engine_locked
        failure = next(f for f in model.failures if f.catastrophic)
        assert failure.mechanism == FailureMechanism.ROD_INSTANT_BEND
        # 1.º ciclo da ordem 1-3-4-2 após t = 0: cilindro 3 em 0,006 s
        assert failure.t_sim_s == pytest.approx(0.006)
        assert failure.component_id == "rod:3"

    def test_bearings_get_quarter_of_rod_damage(self, make_model: ModelFactory) -> None:
        model = make_model()
        event = make_event(1, 0.0005, 5000.0, rod_force_n=57_200.0)
        state = model.step(make_state(1, 0.001, 5000.0, events=[event]), 0.001)
        rod = next(c for c in state.components if c.component_id == "rod:1")
        bearings = next(c for c in state.components if c.component_id == "bearings")
        assert bearings.damage_by_cause["overload"] == pytest.approx(
            0.25 * rod.damage_by_cause["overload"]
        )


class TestOverrev:
    def test_valve_float_damage_per_cycle(self, make_model: ModelFactory) -> None:
        damage, contact = valve_overrev(7400.0, LIMITS, CFG)
        assert damage == pytest.approx(0.008) and contact is False
        assert valve_overrev(7200.0, LIMITS, CFG) == (0.0, False)
        model = make_model()
        event = make_event(2, 0.0005, 7400.0)
        state = model.step(make_state(1, 0.001, 7400.0, events=[event]), 0.001)
        valves = next(c for c in state.components if c.component_id == "valves:2")
        assert 1.0 - valves.health == pytest.approx(0.008)

    def test_valve_piston_contact_at_108_pct(self, make_model: ModelFactory) -> None:
        rpm = 1.08 * 7200.0
        assert valve_overrev(rpm, LIMITS, CFG)[1] is True
        model = make_model()
        event = make_event(3, 0.0005, rpm)
        state = model.step(make_state(1, 0.001, rpm, events=[event]), 0.001)
        assert state.engine_locked
        failure = state.new_failures[0]
        assert (failure.mode, failure.mechanism) == (
            FailureMode.PISTON_FAILURE,
            FailureMechanism.VALVE_PISTON_CONTACT,
        )
        assert failure.cylinder == 3

    def test_no_damage_below_float_and_max_rpm(self, make_model: ModelFactory) -> None:
        model = make_model()
        state = Driver(model, 6700.0).advance(2.0)
        assert state is not None
        assert all(c.health == 1.0 for c in state.components)

    def test_bearing_overrev_rate(self, make_model: ModelFactory) -> None:
        assert bearing_overrev_rate(6800.0, LIMITS, CFG) == 0.0
        assert bearing_overrev_rate(7140.0, LIMITS, CFG) == pytest.approx(0.4 * 0.05)
        model = make_model()
        state = Driver(model, 7140.0, event_factory=make_event).advance(1.0)
        assert state is not None
        bearings = next(c for c in state.components if c.component_id == "bearings")
        assert bearings.damage_by_cause["overrev"] == pytest.approx(0.02, rel=1e-6)


class TestTurbo:
    def test_overspeed_rate(self) -> None:
        assert turbo_overspeed(210_000.0, LIMITS, CFG) == (0.0, False)
        assert turbo_overspeed(1.05 * 210_000.0, LIMITS, CFG)[0] == pytest.approx(0.05)
        assert turbo_overspeed(1.12 * 210_000.0, LIMITS, CFG)[1] is True
        assert turbo_overspeed(None, LIMITS, CFG) == (0.0, False)

    def test_105_pct_for_10_s_halves_health(self, make_model: ModelFactory) -> None:
        model = make_model()
        state = Driver(
            model, 0.0, state_overrides=lambda _t: {"turbo_rpm": 1.05 * 210_000.0}
        ).advance(10.0)
        assert state is not None
        turbine = next(c for c in state.components if c.component_id == "turbo:turbine")
        assert 1.0 - turbine.health == pytest.approx(0.50, rel=0.01)

    def test_112_pct_bursts_on_the_tick(self, make_model: ModelFactory) -> None:
        model = make_model()
        state = model.step(make_state(1, 0.001, 0.0, turbo_rpm=1.12 * 210_000.0), 0.001)
        assert state.engine_locked
        assert state.new_failures[0].mechanism == FailureMechanism.TURBO_OVERSPEED_BURST


class TestHeadGasket:
    def test_peak_pressure_damage(self, make_model: ModelFactory) -> None:
        assert peak_pressure_damage(13_200.0, LIMITS, CFG) == pytest.approx(0.001)
        assert peak_pressure_damage(11_900.0, LIMITS, CFG) == 0.0
        model = make_model()
        event = make_event(1, 0.0005, 5000.0, p_max_kpa=13_200.0)
        state = model.step(make_state(1, 0.001, 5000.0, events=[event]), 0.001)
        gasket = next(c for c in state.components if c.component_id == "head_gasket")
        assert gasket.damage_by_cause == {"pressure": pytest.approx(0.001)}

    def test_gasket_breaks_at_the_most_loaded_fire_ring(self, make_model: ModelFactory) -> None:
        """Anel de fogo por cilindro: o dano por pressão da junta é o máximo dos anéis."""
        model = make_model()
        events = [make_event(c, 0.0001 * c, 5000.0, p_max_kpa=13_200.0) for c in (1, 2, 3, 4)]
        state = model.step(make_state(1, 0.001, 5000.0, events=events), 0.001)
        gasket = next(c for c in state.components if c.component_id == "head_gasket")
        assert gasket.damage_by_cause == {"pressure": pytest.approx(0.001)}
        again = [make_event(1, 0.0011, 5000.0, p_max_kpa=13_200.0)]
        state = model.step(make_state(2, 0.002, 5000.0, events=again), 0.001)
        gasket = next(c for c in state.components if c.component_id == "head_gasket")
        assert gasket.damage_by_cause == {"pressure": pytest.approx(0.002)}
