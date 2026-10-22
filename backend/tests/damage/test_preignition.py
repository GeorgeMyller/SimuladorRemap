"""Pré-ignição por ponto quente, LSPI e mega-knock (T131; RF-07 a RF-09)."""

from __future__ import annotations

import math

import pytest
from kfm_helpers import SPEC_CONFIG, Driver, ModelFactory, make_event, spec_config

from simremap.damage.config import DamageConfig
from simremap.damage.contracts import FailureMechanism, FailureMode, KnockClass
from simremap.damage.digest import damage_streams
from simremap.damage.preignition import (
    PreignitionState,
    hot_spot_probability,
    iat_factor,
    load_factor,
    lspi_probability,
    mega_knock_intensity,
    preignition_pressure_kpa,
)

CFG = SPEC_CONFIG
NO_RUNAWAY = spec_config(preignition_runaway_cycles=0)
THR = CFG.preignition_threshold_for("e27")


def _count(cfg: DamageConfig, seed: int, cycles: int, p_hot: float, p_lspi: float) -> list[int]:
    streams = damage_streams(seed)
    state = PreignitionState(1, cfg, streams.preignition, streams.lspi)
    return [k for k in range(cycles) if state.evaluate(1, p_hot, p_lspi) is not None]


class TestHotSpot:
    def test_inactive_below_window(self) -> None:
        p = hot_spot_probability(THR - 61.0, THR, 40.0, 200.0, CFG)
        assert p == 0.0
        assert _count(CFG, 42, 10_000, p, 0.0) == []

    def test_rate_matches_p0_e2(self) -> None:
        p = hot_spot_probability(THR + 30.0, THR, 40.0, 200.0, CFG)
        assert p == pytest.approx(1e-3 * math.e**2)
        hits = _count(NO_RUNAWAY, 42, 100_000, p, 0.0)
        assert len(hits) / 100_000 == pytest.approx(1e-3 * math.e**2, rel=0.10)

    def test_same_seed_same_cycles(self) -> None:
        p = hot_spot_probability(THR + 30.0, THR, 40.0, 200.0, CFG)
        assert _count(CFG, 9, 20_000, p, 0.0) == _count(CFG, 9, 20_000, p, 0.0)

    def test_factors_and_cap(self) -> None:
        assert iat_factor(40.0, CFG) == 1.0
        assert iat_factor(-100.0, CFG) == 0.5 and iat_factor(200.0, CFG) == 4.0
        assert load_factor(200.0, CFG) == 1.0
        assert hot_spot_probability(THR + 500.0, THR, 80.0, 300.0, CFG) == 0.3


class TestLspi:
    def test_pfi_never(self) -> None:
        assert lspi_probability("pfi", 2500.0, 2100.0, 40.0, CFG) == 0.0

    def test_gdi_rate(self) -> None:
        p = lspi_probability("gdi", 2500.0, 2100.0, 40.0, CFG)
        assert p == pytest.approx(9e-4)
        hits = _count(NO_RUNAWAY, 42, 200_000, 0.0, p)
        assert len(hits) / 200_000 == pytest.approx(9e-4, rel=0.10)

    def test_outside_window(self) -> None:
        assert lspi_probability("gdi", 3100.0, 2100.0, 40.0, CFG) == 0.0
        assert lspi_probability("gdi", 2500.0, 1400.0, 40.0, CFG) == 0.0
        assert lspi_probability("gdi", 2500.0, 9000.0, 40.0, CFG) == 2e-3
        assert lspi_probability("gdi", 2500.0, 2100.0, 40.0, spec_config(lspi_enabled=False)) == 0


class TestMegaKnock:
    def test_pressure_and_intensity(self) -> None:
        p_pi = preignition_pressure_kpa(9000.0, 35.0, 15.0, CFG)
        assert p_pi == pytest.approx(15_300.0)
        assert mega_knock_intensity(p_pi, CFG) == pytest.approx(38.25)

    def test_runaway_for_10_cycles(self) -> None:
        streams = damage_streams(1)
        state = PreignitionState(2, CFG, streams.preignition, streams.lspi)
        assert state.evaluate(1, 1.0, 0.0) is not None
        multipliers = []
        for _ in range(11):
            multipliers.append(state.multiplier(1))
            state.evaluate(1, 0.0, 0.0)
        assert multipliers == [3.0] * 10 + [1.0]
        assert state.multiplier(2) == 1.0
        state.reset()
        assert state.runaway == [0, 0]

    def test_model_preignition_cycle_is_severe_and_damages_piston(
        self, make_model: ModelFactory
    ) -> None:
        model = make_model()
        hot = {"hot_spot_temp_c": [500.0, THR + 100.0, 500.0, 500.0]}
        driver = Driver(
            model,
            5000.0,
            event_factory=lambda c, t, rpm: make_event(c, t, rpm, imep_kpa=1000.0),
            state_overrides=lambda _t: hot,
        )
        for state in driver.run(1.0):
            obs = state.knock_last[1]
            if obs is not None and obs.preignition == "hot_spot":
                assert obs.knock_class == KnockClass.SEVERE
                assert obs.p_preignition_kpa == pytest.approx(15_300.0)
                assert obs.intensity == pytest.approx(38.25)
                piston = next(c for c in state.components if c.component_id == "piston:2")
                assert piston.damage_by_cause["preignition"] >= 0.15 * 15_300 / 12_000 - 1e-9
                return
        pytest.fail("nenhuma pré-ignição em 1 s com p = 0,3 por ciclo")

    def test_preignition_above_limit_is_catastrophic(self, make_model: ModelFactory) -> None:
        model = make_model()
        driver = Driver(
            model,
            2500.0,
            event_factory=lambda c, t, rpm: make_event(c, t, rpm, p_max_kpa=10_000.0),
            state_overrides=lambda _t: {"hot_spot_temp_c": THR + 100.0},
        )
        state = driver.advance(2.0, until_locked=True)
        assert state is not None and state.engine_locked
        failure = next(f for f in model.failures if f.catastrophic)
        assert failure.mode == FailureMode.PRE_IGNITION
        assert failure.mechanism in (FailureMechanism.HOT_SPOT_PREIGNITION, FailureMechanism.LSPI)

    def test_lspi_failure_in_gdi_hold(self, make_model: ModelFactory) -> None:
        cfg = spec_config(lspi_p_base=1.0e-2, lspi_p_max=0.5)
        model = make_model(cfg)
        driver = Driver(
            model,
            2000.0,
            event_factory=lambda c, t, rpm: make_event(
                c, t, rpm, p_max_kpa=10_000.0, imep_kpa=2100.0
            ),
        )
        driver.advance(5.0, until_locked=True)
        failure = next(f for f in model.failures if f.catastrophic)
        assert (failure.mode, failure.mechanism) == (
            FailureMode.PRE_IGNITION,
            FailureMechanism.LSPI,
        )
