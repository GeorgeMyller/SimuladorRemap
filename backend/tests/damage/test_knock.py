"""Douaud-Eyzat, Livengood-Wu, MAPO, classes e dano por knock (T129; RF-01 a RF-04, RF-11)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from kfm_helpers import (
    E27_MON,
    E27_RON,
    SPEC_CONFIG,
    Driver,
    ModelFactory,
    make_event,
    t_unburned_for_tau,
)

from simremap.damage.contracts import KnockClass, classify_knock
from simremap.damage.errors import DamageError
from simremap.damage.knock import (
    douaud_eyzat_tau_ms,
    evaluate_knock,
    fuel_energy_j,
    knock_piston_damage,
    knock_temp_step,
    livengood_wu_integral,
    ms_per_degree,
    octane_number,
    validate_event,
)

CFG = SPEC_CONFIG


def _reference_tau(p_kpa: float, t_k: float, octane: float) -> float:
    octane_term: float = (octane / 100) ** 3.402
    pressure_term: float = (p_kpa / 101.325) ** -1.7
    return 17.68 * octane_term * pressure_term * math.exp(3800 / t_k)


class TestDouaudEyzat:
    def test_octane_is_mean_of_ron_and_mon(self) -> None:
        assert octane_number(E27_RON, E27_MON) == 88.0

    def test_tau_reference_point(self) -> None:
        tau = douaud_eyzat_tau_ms(np.array([6079.5]), np.array([900.0]), 88.0, CFG)
        assert tau[0] == pytest.approx(0.740, rel=5e-3)

    def test_tau_saturates_at_low_temperature_or_pressure(self) -> None:
        tau = douaud_eyzat_tau_ms(np.array([6000.0, 40.0]), np.array([350.0, 900.0]), 88.0, CFG)
        assert tau.tolist() == [1e6, 1e6]

    @settings(max_examples=200, deadline=None)
    @given(
        p=st.floats(60.0, 20_000.0),
        t=st.floats(400.0, 1400.0),
        octane=st.floats(80.0, 110.0),
    )
    def test_tau_matches_reference_float64(self, p: float, t: float, octane: float) -> None:
        tau = douaud_eyzat_tau_ms(np.array([p]), np.array([t]), octane, CFG)[0]
        ref = min(_reference_tau(p, t, octane), 1e6)
        assert tau == pytest.approx(ref, rel=5e-3)


class TestLivengoodWu:
    def test_ms_per_degree(self) -> None:
        assert ms_per_degree(6000.0) == pytest.approx(0.02778, rel=1e-3)
        assert ms_per_degree(3000.0) == pytest.approx(0.05556, rel=1e-3)

    def test_constant_tau_crosses_on_eighth_point(self) -> None:
        integral = livengood_wu_integral(np.full(20, 0.4), 3000.0)
        k = int(np.flatnonzero(integral >= 1.0)[0])
        assert k == 7
        assert integral[k] == pytest.approx(1.111, rel=1e-3)

    def _tau_event(self, xb_at_8th: float) -> object:
        p = 5000.0
        t_u = t_unburned_for_tau(0.4, p)
        event = make_event(1, 1.0, 3000.0)
        xb = [min(0.999, 0.05 * i) for i in range(20)]
        xb[7] = xb_at_8th
        return event.model_copy(
            update={
                "pressure_kpa": [p] * 20,
                "t_unburned_k": [t_u] * 20,
                "burned_fraction": xb,
                "theta_start_deg": -10.0,
            }
        )

    def test_event_knock_onset_and_integral(self) -> None:
        event = self._tau_event(0.35)
        result = evaluate_knock(event, 2000.0, CFG)  # type: ignore[arg-type]
        assert result.theta_onset_deg_atdc == -10.0 + 7
        reference = sum(ms_per_degree(3000.0) / 0.4 for _ in range(20))
        assert result.lw_integral_end == pytest.approx(reference, rel=5e-3)

    def test_onset_after_end_of_combustion_is_no_knock(self) -> None:
        result = evaluate_knock(self._tau_event(0.98), 2000.0, CFG)  # type: ignore[arg-type]
        assert result.knock_class == KnockClass.NONE
        assert result.intensity == 0.0
        assert result.theta_onset_deg_atdc is None

    def test_misfire_and_fuel_cut_are_silent(self) -> None:
        misfire = make_event(1, 1.0, 6000.0, knock=True, misfire=True)
        assert evaluate_knock(misfire, 2000.0, CFG).intensity == 0.0
        no_rpm = make_event(1, 1.0, 6000.0, knock=True).model_copy(update={"rpm": 0.0})
        assert evaluate_knock(no_rpm, 2000.0, CFG).knock_class == KnockClass.NONE

    def test_no_crossing_gives_zero(self) -> None:
        result = evaluate_knock(make_event(1, 1.0, 6000.0), 2000.0, CFG)
        assert (result.intensity, result.knock_energy_j, result.mapo_kpa) == (0.0, 0.0, 0.0)
        assert 0.0 < result.lw_integral_end < 1.0


class TestMapo:
    def test_mapo_intensity_and_autoignited_fraction(self) -> None:
        event = make_event(1, 1.0, 6000.0, knock=True, xb_k=0.80, p_k=8000.0)
        result = evaluate_knock(event, 1935.0, CFG)
        assert result.mapo_kpa == pytest.approx(800.0)
        assert result.intensity == pytest.approx(8.0)
        assert result.autoignited_fraction == pytest.approx(0.20)
        assert result.knock_energy_j == pytest.approx(387.0)
        assert result.knock_class == KnockClass.SEVERE

    def test_fuel_energy(self) -> None:
        assert fuel_energy_j(45.0, 1000.0, 13.2, 43.0, 1.0) == pytest.approx(1935.0)
        # pobre em ar: limitado por m_ar / AFR
        assert fuel_energy_j(45.0, 132.0, 13.2, 43.0, 1.0) == pytest.approx(430.0)


class TestClasses:
    @pytest.mark.parametrize(
        ("intensity", "expected"),
        [
            (0.29, KnockClass.NONE),
            (0.30, KnockClass.LIGHT),
            (1.00, KnockClass.MODERATE),
            (3.00, KnockClass.SEVERE),
        ],
    )
    def test_boundaries(self, intensity: float, expected: KnockClass) -> None:
        assert classify_knock(intensity) == expected


class TestInputValidation:
    def test_mismatched_vectors(self) -> None:
        event = make_event(2, 1.0, 6000.0).model_copy(update={"t_unburned_k": [700.0]})
        with pytest.raises(DamageError) as info:
            validate_event(event)
        assert info.value.error_code == "DAMAGE_INPUT_INVALID"

    def test_non_finite_values(self) -> None:
        event = make_event(2, 1.0, 6000.0).model_copy(update={"pressure_kpa": [float("nan")] * 40})
        with pytest.raises(DamageError, match="NaN"):
            validate_event(event)


class TestKnockDamage:
    def test_below_safe_intensity_no_damage(self) -> None:
        assert knock_piston_damage(0.9, 387.0, CFG) == 0.0

    def test_severe_cycle_damage(self) -> None:
        damage = knock_piston_damage(8.0, 387.0, CFG)
        assert damage == pytest.approx(4.06e-3, rel=1e-2)
        assert CFG.head_gasket_knock_share * damage == pytest.approx(1.22e-3, rel=1e-2)

    def test_knock_temperature_first_order(self) -> None:
        y = 0.0
        for _ in range(15_000):  # 15 s = 10 τ
            y = knock_temp_step(y, 8.0, 0.001, CFG)
        assert y == pytest.approx(25.0 * 7.0, rel=1e-3)
        assert knock_temp_step(10.0, 0.5, 0.001, CFG) < 10.0

    def test_continuous_severe_knock_destroys_piston_in_4_9_s(
        self, make_model: ModelFactory
    ) -> None:
        model = make_model()
        driver = Driver(
            model,
            6000.0,
            event_factory=lambda c, t, rpm: make_event(c, t, rpm, knock=c == 3),
        )
        state = driver.advance(10.0, until_locked=True)
        assert state is not None and state.engine_locked
        failure = next(f for f in model.failures if f.catastrophic)
        assert failure.component_id == "piston:3"
        assert failure.mechanism.value == "knock_erosion"
        assert failure.t_sim_s == pytest.approx(4.9, rel=0.10)
        gasket = next(c for c in state.components if c.component_id == "head_gasket")
        piston_damage = 1.0  # o pistão foi a 0
        assert gasket.damage_by_cause["knock"] == pytest.approx(0.3 * piston_damage, rel=0.02)
        assert state.knock_last[2] is not None
        assert state.knock_last[2].knock_class == KnockClass.SEVERE
