"""Saúde por componente, Larson-Miller com Robinson e lambda pobre (T132; RF-10, RF-12, RF-13)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from kfm_helpers import SPEC_CONFIG, Driver, ModelFactory, make_event, make_state

from simremap.catalog.contracts import VehicleSpec
from simremap.damage.contracts import FailureMechanism, FailureMode
from simremap.damage.thermal import (
    creep_damage,
    larson_miller_reference,
    lean_delta_c,
    metal_temp_step,
    rupture_time_s,
)

CFG = SPEC_CONFIG


class TestComponents:
    def test_hatch_has_15_components(self, make_model: ModelFactory) -> None:
        model = make_model()
        ids = model.component_ids
        assert len(ids) == 15
        assert ids[:4] == ["piston:1", "piston:2", "piston:3", "piston:4"]
        assert ids[-3:] == ["head_gasket", "bearings", "turbo:turbine"]
        state = model.step(make_state(1, 0.001, 0.0), 0.001)
        assert all(c.health == 1.0 and c.virtual_health == 1.0 for c in state.components)

    def test_v8_has_26_components_without_turbine(
        self, make_model: ModelFactory, v8_vehicle: VehicleSpec
    ) -> None:
        model = make_model(vehicle=v8_vehicle)
        assert len(model.component_ids) == 26
        assert "turbo:turbine" not in model.component_ids
        state = model.step(
            make_state(1, 0.001, 3000.0, n_cyl=8, turbo_rpm=None, egt_collector_c=1100.0), 0.001
        )
        assert not any(f.mode == FailureMode.TURBO_MELTDOWN for f in state.new_failures)

    @settings(max_examples=25, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.floats(0.0, 8000.0),  # rpm
                st.floats(200.0, 500.0),  # torque
                st.floats(800.0, 1150.0),  # EGT pré-turbina
                st.booleans(),  # knock
            ),
            min_size=5,
            max_size=40,
        )
    )
    def test_health_never_increases_without_restore(
        self, steps: list[tuple[float, float, float, bool]]
    ) -> None:
        from kfm_helpers import build_e27, build_hatch

        from simremap.damage.model import DamageModel

        model = DamageModel(CFG, build_hatch(), build_e27(), 3)
        previous = np.ones(15)
        for k, (rpm, torque, egt, knock) in enumerate(steps, start=1):
            events = [make_event(1 + k % 4, k * 0.001 - 0.0005, rpm, knock=knock)] if rpm else []
            state = model.step(
                make_state(k, k * 0.001, rpm, events=events, torque_nm=torque, egt_collector_c=egt),
                0.001,
            )
            health = np.array([c.health for c in state.components])
            assert (health <= previous + 1e-15).all()
            assert ((health >= 0.0) & (health <= 1.0)).all()
            previous = health


class TestLarsonMiller:
    def test_reference_numbers_of_the_turbine(self) -> None:
        lmp = larson_miller_reference(950.0, 120.0, 20.0)
        assert lmp == pytest.approx(22_656.0, abs=1.0)
        assert rupture_time_s(1000.0, lmp, 20.0) == pytest.approx(22.5, rel=0.01)
        assert rupture_time_s(950.0, lmp, 20.0) == pytest.approx(120.0)

    def test_no_damage_at_or_below_limit_for_600_s(self) -> None:
        total = 0.0
        for _ in range(600_000):
            total += creep_damage(950.0, 950.0, 120.0, 0.001, CFG)
        assert total == 0.0
        assert creep_damage(951.0, 950.0, 120.0, 0.001, CFG) > 0.0

    def test_turbine_at_1000_c_fails_in_22_5_s(self, make_model: ModelFactory) -> None:
        model = make_model()
        driver = Driver(model, 0.0, state_overrides=lambda _t: {"egt_collector_c": 1000.0})
        state = driver.advance(40.0, until_locked=True)
        assert state is not None and state.engine_locked
        failure = next(f for f in model.failures if f.catastrophic)
        assert failure.component_id == "turbo:turbine"
        assert (failure.mode, failure.mechanism) == (
            FailureMode.TURBO_MELTDOWN,
            FailureMechanism.TURBINE_CREEP,
        )
        assert failure.t_sim_s == pytest.approx(22.5, rel=0.10)

    def test_turbine_at_950_c_for_600_s_keeps_exact_health(self, make_model: ModelFactory) -> None:
        model = make_model(sim_hz=100)
        driver = Driver(
            model, 0.0, sim_hz=100, state_overrides=lambda _t: {"egt_collector_c": 950.0}
        )
        state = driver.advance(600.0)
        assert state is not None
        assert all(c.health == 1.0 for c in state.components)
        model.step(make_state(60_001, 600.01, 0.0, egt_collector_c=951.0), 0.01)
        turbine = next(c for c in model.components() if c.component_id == "turbo:turbine")
        assert turbine.health < 1.0
        assert turbine.damage_by_cause["thermal"] > 0.0

    def test_exhaust_valve_burn(self, make_model: ModelFactory) -> None:
        model = make_model()
        driver = Driver(
            model, 0.0, state_overrides=lambda _t: {"egt_c": [850.0, 1100.0, 850.0, 850.0]}
        )
        driver.advance(30.0, until_locked=True)
        failure = next(f for f in model.failures if f.catastrophic)
        assert failure.component_id == "valves:2"
        assert (failure.mode, failure.mechanism) == (
            FailureMode.EGT_OVERTEMP,
            FailureMechanism.EXHAUST_VALVE_BURN,
        )

    def test_piston_thermal_melt(self, make_model: ModelFactory) -> None:
        model = make_model()
        driver = Driver(
            model, 0.0, state_overrides=lambda _t: {"piston_temp_c": [100.0, 100.0, 100.0, 380.0]}
        )
        driver.advance(60.0, until_locked=True)
        failure = next(f for f in model.failures if f.catastrophic)
        assert failure.component_id == "piston:4"
        assert failure.mechanism == FailureMechanism.PISTON_THERMAL_MELT


class TestLean:
    def test_lean_delta(self) -> None:
        assert lean_delta_c(0.95, 220.0, CFG) == pytest.approx(42.0)
        assert lean_delta_c(0.95, 140.0, CFG) == 0.0
        assert lean_delta_c(0.85, 220.0, CFG) == 0.0
        assert lean_delta_c(None, 220.0, CFG) == 0.0

    def test_effective_piston_temperature(self, make_model: ModelFactory) -> None:
        model = make_model()
        state = model.step(
            make_state(1, 0.001, 0.0, map_kpa=220.0, lambda_cyl=[0.95, 0.85, None, 0.95]),
            0.001,
        )
        assert state.piston_temp_eff_c == pytest.approx([142.0, 100.0, 100.0, 142.0])

    def test_knock_heats_the_piston(self, make_model: ModelFactory) -> None:
        model = make_model()
        driver = Driver(
            model, 6000.0, event_factory=lambda c, t, r: make_event(c, t, r, knock=c == 1)
        )
        state = driver.advance(1.5)
        assert state is not None
        # 1.ª ordem com τ 1,5 s: ≈ 63 % de 25 · (8 − 1) após 1,5 s
        assert state.piston_temp_eff_c[0] - 100.0 == pytest.approx(0.632 * 175.0, rel=0.05)
        assert state.piston_temp_eff_c[1] == pytest.approx(100.0)


class TestMetalTemperature:
    """Fluência sobre a temperatura de metal de 1ª ordem (calibração 1.2.0)."""

    def test_metal_temp_step(self) -> None:
        assert metal_temp_step(math.nan, 900.0, 0.001, 5.0) == 900.0
        step = metal_temp_step(500.0, 1500.0, 0.001, 5.0)
        assert step == pytest.approx(500.0 + 1000.0 * (1.0 - math.exp(-0.001 / 5.0)))

    def test_short_gas_spike_does_not_burn_the_valve(self, make_model: ModelFactory) -> None:
        """Pico de 1800 °C de gás por 0,3 s (transitório rico) com metal a 850 °C: sem dano."""
        model = make_model()

        def egt(t: float) -> dict[str, Any]:
            hot = 1.0 <= t < 1.3
            return {"egt_c": [1800.0 if hot else 850.0] * 4, "egt_collector_c": 850.0}

        driver = Driver(model, 3000.0, state_overrides=egt)
        state = driver.advance(3.0)
        assert state is not None
        assert all(c.health == 1.0 for c in state.components if c.component_id.startswith("valves"))

    def test_sustained_overtemperature_still_burns_the_valve(
        self, make_model: ModelFactory
    ) -> None:
        model = make_model()
        driver = Driver(
            model,
            3000.0,
            state_overrides=lambda _t: {"egt_c": [850.0, 1300.0, 850.0, 850.0]},
        )
        driver.advance(60.0, until_locked=True)
        failure = next(f for f in model.failures if f.catastrophic)
        assert failure.component_id == "valves:2"
