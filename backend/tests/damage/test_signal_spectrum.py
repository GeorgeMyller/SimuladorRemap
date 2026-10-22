"""Sinal de knock para a ECU e espectro sintético de 256 bins (T130; RF-05, RF-06; D-BUS-10)."""

from __future__ import annotations

import numpy as np
import pytest
from kfm_helpers import SPEC_CONFIG, Driver, ModelFactory, make_event, make_state, spec_config

from simremap.damage.digest import damage_streams
from simremap.damage.signal import KnockSignalGenerator, in_sensor_window, noise_floor
from simremap.damage.spectrum import (
    BIN_WIDTH_HZ,
    SpectrumGenerator,
    draper_frequencies_hz,
    floor_spectrum,
    speed_of_sound_m_s,
)
from simremap.telemetry.contracts import KnockSpectrum

QUIET = spec_config(knock_noise_sigma=0.0)


def _one_cycle(make_model: ModelFactory, theta_onset: float, rpm: float = 5000.0) -> list[float]:
    model = make_model(QUIET)
    event = make_event(3, 0.0005, rpm, knock=True, xb_k=0.8, p_k=4000.0, theta_onset=theta_onset)
    model.step(make_state(1, 0.001, rpm, events=[event]), 0.001)
    return model.knock_signal().intensity


class TestKnockSignal:
    def test_noise_floor(self) -> None:
        assert noise_floor(0.0, QUIET) == pytest.approx(0.05)
        assert noise_floor(7000.0, QUIET) == pytest.approx(0.15)

    def test_in_window_signal_is_gain_times_intensity_plus_floor(
        self, make_model: ModelFactory
    ) -> None:
        values = _one_cycle(make_model, 20.0)
        assert values[2] == pytest.approx(4.0 + noise_floor(5000.0, QUIET))
        assert values[0] == 0.0  # sem evento no cilindro 1: valor retido (0)

    def test_outside_window_only_floor(self, make_model: ModelFactory) -> None:
        values = _one_cycle(make_model, 70.0)
        assert values[2] == pytest.approx(noise_floor(5000.0, QUIET))

    def test_window_edges(self) -> None:
        assert in_sensor_window(-5.0, QUIET) and in_sensor_window(60.0, QUIET)
        assert not in_sensor_window(-5.1, QUIET) and not in_sensor_window(None, QUIET)

    def test_end_cylinders_have_lower_gain(self) -> None:
        assert QUIET.sensor_gains(4) == [0.85, 1.0, 1.0, 0.85]

    def test_value_is_held_until_next_event(self, make_model: ModelFactory) -> None:
        model = make_model(QUIET)
        event = make_event(2, 0.0005, 5000.0, knock=True, p_k=4000.0, theta_onset=10.0)
        model.step(make_state(1, 0.001, 5000.0, events=[event]), 0.001)
        held = model.knock_signal().intensity[1]
        model.step(make_state(2, 0.002, 5000.0), 0.001)
        assert model.knock_signal().intensity[1] == held

    def test_same_seed_same_sequence_for_10000_events(self) -> None:
        def sequence(seed: int) -> list[float]:
            gen = KnockSignalGenerator(4, SPEC_CONFIG, damage_streams(seed).knock_noise)
            return [gen.on_cycle(1 + i % 4, 2.0, 10.0, 5000.0) for i in range(10_000)]

        first, second = sequence(42), sequence(42)
        assert first == second
        assert sequence(43) != first
        noisy = np.array(first) - 2.0 * np.array([0.85, 1.0, 1.0, 0.85] * 2500)
        assert float(np.median(noisy / noise_floor(5000.0, QUIET))) == pytest.approx(1.0, rel=0.05)

    def test_signal_feature_off_is_silent(self, make_model: ModelFactory) -> None:
        cfg = spec_config(features=("knock", "thermal", "mechanical", "damage_off"))
        model = make_model(cfg)
        event = make_event(3, 0.0005, 5000.0, knock=True, theta_onset=10.0)
        state = model.step(make_state(1, 0.001, 5000.0, events=[event]), 0.001)
        assert state.knock_signal.intensity == [0.0] * 4


class TestSpectrum:
    def test_draper_modes_of_the_hatch(self) -> None:
        f10, f20, f01, f30 = draper_frequencies_hz(82.5, 1.28, 2500.0)
        assert speed_of_sound_m_s(1.28, 2500.0) == pytest.approx(958.3, rel=1e-3)
        assert f10 == pytest.approx(6800.0, abs=50.0)
        assert f20 == pytest.approx(11_300.0, rel=0.01)
        assert f01 == pytest.approx(14_200.0, rel=0.01)
        assert f30 > f01

    def test_severe_cycle_peak_at_first_mode(self) -> None:
        gen = SpectrumGenerator(82.5, SPEC_CONFIG, damage_streams(42).spectrum)
        gen.observe(6.0)
        frame = gen.frame(1.0, 6000.0)
        assert len(frame.bins_hz) == 256 and len(frame.magnitude_db) == 256
        assert frame.bins_hz[1] == pytest.approx(78.125) == BIN_WIDTH_HZ
        peak = frame.bins_hz[int(np.argmax(frame.magnitude_db))]
        assert abs(peak - frame.resonance_hz[0]) <= BIN_WIDTH_HZ
        assert frame.intensity_max == 6.0

    def test_no_knock_stays_within_6_db_of_floor(self) -> None:
        gen = SpectrumGenerator(82.5, SPEC_CONFIG, damage_streams(7).spectrum)
        floor_db = 10.0 * np.log10(floor_spectrum(6000.0, SPEC_CONFIG))
        for k in range(200):
            frame = gen.frame(k * 0.02, 6000.0)
            assert float(np.max(np.array(frame.magnitude_db) - floor_db)) <= 6.0

    def test_accumulator_resets_after_frame(self) -> None:
        gen = SpectrumGenerator(82.5, SPEC_CONFIG, damage_streams(1).spectrum)
        gen.observe(5.0)
        gen.observe(2.0)
        assert gen.i_max == 5.0
        gen.frame(0.02, 3000.0)
        assert gen.i_max == 0.0

    def test_to_telemetry_contract(self) -> None:
        gen = SpectrumGenerator(82.5, SPEC_CONFIG, damage_streams(1).spectrum)
        out = gen.frame(0.0, 3000.0).to_telemetry()
        assert isinstance(out, KnockSpectrum)
        assert len(out.resonance_hz) == 4 and out.sensor == "block"

    def test_model_spectrum_uses_max_cycle_of_frame(self, make_model: ModelFactory) -> None:
        model = make_model()
        driver = Driver(
            model,
            6000.0,
            event_factory=lambda c, t, rpm: make_event(c, t, rpm, knock=c == 2, theta_onset=10.0),
        )
        driver.advance(0.02)
        frame = model.spectrum_frame(0.02)
        assert frame.intensity_max == pytest.approx(8.0)
        assert frame.rpm == 6000.0
